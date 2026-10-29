/** Web Bluetooth transport for DeTong DP-series label printers. */

const SERVICE = "0000ff00-0000-1000-8000-00805f9b34fb";
const CH_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb";
const CH_REPLY = "0000ff01-0000-1000-8000-00805f9b34fb";
const CH_EVENT = "0000ff03-0000-1000-8000-00805f9b34fb";

const CHUNK = 512;
const CREDIT_TIMEOUT_MS = 2000;

export function isSupported(): boolean {
  return typeof navigator !== "undefined" && "bluetooth" in navigator;
}

export class Printer {
  private device?: BluetoothDevice;
  private writeChar?: BluetoothRemoteGATTCharacteristic;
  private replyChar?: BluetoothRemoteGATTCharacteristic;
  private eventChar?: BluetoothRemoteGATTCharacteristic;
  private credits = 0;
  private creditWaiters: Array<() => void> = [];
  private replies: Uint8Array[] = [];
  private replyWaiters: Array<() => void> = [];

  get name(): string {
    return this.device?.name ?? "(unknown)";
  }

  get connected(): boolean {
    return !!this.device?.gatt?.connected;
  }

  /** Must be called from a user gesture. */
  async request(acceptAll = false): Promise<void> {
    if (!isSupported()) {
      throw new Error("this browser has no Web Bluetooth (use Chrome or Edge)");
    }
    const options: RequestDeviceOptions = acceptAll
      ? { acceptAllDevices: true, optionalServices: [SERVICE] }
      : { filters: [{ namePrefix: "DP" }, { namePrefix: "DT" }], optionalServices: [SERVICE] };
    this.device = await navigator.bluetooth.requestDevice(options);
    this.device.addEventListener("gattserverdisconnected", () => {
      this.writeChar = this.replyChar = this.eventChar = undefined;
    });
  }

  async connect(): Promise<void> {
    if (!this.device?.gatt) throw new Error("no device selected");
    const server = await this.device.gatt.connect();
    const service = await server.getPrimaryService(SERVICE);
    this.writeChar = await service.getCharacteristic(CH_WRITE);
    this.replyChar = await service.getCharacteristic(CH_REPLY);
    this.eventChar = await service.getCharacteristic(CH_EVENT);

    await this.replyChar.startNotifications();
    this.replyChar.addEventListener("characteristicvaluechanged", (event) => {
      const value = (event.target as BluetoothRemoteGATTCharacteristic).value;
      if (value) this.replies.push(new Uint8Array(value.buffer.slice(0)));
      this.wakeReply();
    });
    await this.eventChar.startNotifications();
    this.eventChar.addEventListener("characteristicvaluechanged", (event) => {
      const value = (event.target as BluetoothRemoteGATTCharacteristic).value;
      if (value && value.byteLength === 2 && value.getUint8(0) === 1 && value.getUint8(1) === 1) {
        this.credits += 1;
        const waiter = this.creditWaiters.shift();
        waiter?.();
      }
    });
  }

  private wakeReply(): void {
    const waiter = this.replyWaiters.shift();
    waiter?.();
  }

  private waitCredit(): Promise<void> {
    return new Promise((resolve) => {
      if (this.credits > 0) {
        this.credits -= 1;
        resolve();
        return;
      }
      const timer = setTimeout(() => {
        this.creditWaiters = this.creditWaiters.filter((w) => w !== arm);
        resolve();
      }, CREDIT_TIMEOUT_MS);
      const arm = () => {
        clearTimeout(timer);
        this.credits = Math.max(0, this.credits - 1);
        resolve();
      };
      this.creditWaiters.push(arm);
    });
  }

  private async write(chunk: Uint8Array): Promise<void> {
    const char = this.writeChar;
    if (!char) throw new Error("not connected");
    const view = chunk as unknown as BufferSource;
    if (char.properties.writeWithoutResponse) {
      await char.writeValueWithoutResponse(view);
    } else {
      await char.writeValueWithResponse(view);
    }
  }

  async send(stream: Uint8Array, onProgress?: (sent: number, total: number) => void): Promise<void> {
    const total = stream.length;
    let outstanding = 0;
    const window = 8;
    for (let off = 0; off < total; off += CHUNK) {
      if (outstanding >= window) {
        await this.waitCredit();
        outstanding = Math.max(0, outstanding - 1);
      }
      await this.write(stream.subarray(off, Math.min(off + CHUNK, total)));
      outstanding += 1;
      onProgress?.(Math.min(off + CHUNK, total), total);
    }
    // drain the tail so the printer's UART buffer flushes before we disconnect
    const deadline = Date.now() + 5000;
    while (outstanding > 0 && Date.now() < deadline) {
      await Promise.race([this.waitCredit(), new Promise((r) => setTimeout(r, 300))]);
      outstanding -= 1;
    }
  }

  async query(type: number, timeoutMs = 2000): Promise<Uint8Array | null> {
    const char = this.writeChar;
    if (!char) throw new Error("not connected");
    this.replies = [];
    const frame = new Uint8Array([0x1f, type, 0x00]);
    let sum = 0;
    for (const b of frame.slice(1)) sum += b;
    const payload = Uint8Array.from([...frame, ~sum & 0xff]);
    await char.writeValueWithResponse(payload);
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (this.replies.length) return this.replies[0];
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, 100);
        this.replyWaiters.push(() => {
          clearTimeout(timer);
          resolve();
        });
      });
    }
    return null;
  }

  describeStatus(status: Uint8Array | null): string {
    if (!status || status.length < 4) return "unknown";
    const code = status[3];
    return code === 0x00 ? "ready (0x00)" : `status 0x${code.toString(16).padStart(2, "0").toUpperCase()}`;
  }

  disconnect(): void {
    this.device?.gatt?.disconnect();
  }
}
