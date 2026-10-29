/**
 * Web Bluetooth transport for DeTong DP-series label printers.
 *
 * GATT layout (reverse engineered from the DP305P):
 *   ff00/ff02  write / write-without-response  -> printer
 *   ff00/ff01  notify                          -> one protocol reply per frame
 *   ff00/ff03  notify                          -> `01 01` credit after each write
 *
 * Chrome only shows a device in the chooser when it advertises a matching name,
 * and it can only use a characteristic if its service is listed in
 * `optionalServices` — both are easy to get wrong, hence the step logging and
 * the "show all devices" fallback.
 */

const SERVICE = "0000ff00-0000-1000-8000-00805f9b34fb";
const CH_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb";
const CH_REPLY = "0000ff01-0000-1000-8000-00805f9b34fb";
const CH_EVENT = "0000ff03-0000-1000-8000-00805f9b34fb";

const CHUNK = 512;
const CREDIT_TIMEOUT_MS = 1500;
const NAME_PREFIXES = ["DP", "DT", "DeTong", "DETONG"];

export type Step = (message: string) => void;

export function isSupported(): boolean {
  return typeof navigator !== "undefined" && "bluetooth" in navigator;
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/** Management command frame: <1f> <type> <len> <payload> <checksum>. */
export function mgmtFrame(type: number, payload: Uint8Array = new Uint8Array()): Uint8Array {
  const body = [0x1f, type, payload.length, ...payload];
  // the checksum covers everything after the group byte
  const sum = body.slice(1).reduce((a, b) => a + b, 0);
  return Uint8Array.from([...body, ~sum & 0xff]);
}

function describeError(err: unknown): string {
  if (err instanceof DOMException) {
    switch (err.name) {
      case "NotFoundError":
        return "デバイスが選ばれませんでした（キャンセル、または一覧に出ていない）";
      case "SecurityError":
        return "Bluetooth の利用が許可されていません（ブラウザ/OS の設定を確認）";
      case "NetworkError":
        return "接続に失敗しました（プリンタが他の端末に繋がっている可能性）";
      case "NotSupportedError":
        return "このブラウザ/このサービスには Web Bluetooth がありません";
      case "InvalidStateError":
        return "Bluetooth アダプタの状態が不正です";
      default:
        return `${err.name}: ${err.message}`;
    }
  }
  return err instanceof Error ? err.message : String(err);
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
    return !!this.device?.gatt?.connected && !!this.writeChar;
  }

  get mtu(): number | null {
    const gatt = this.device?.gatt as unknown as { mtu?: number } | undefined;
    return typeof gatt?.mtu === "number" ? gatt.mtu : null;
  }

  /**
   * Ask Chrome for a device. Must be called from a user gesture.
   * `acceptAll` widens the chooser for printers whose advertised name is odd.
   */
  async request(acceptAll = false): Promise<string> {
    if (!isSupported()) {
      throw new Error("Web Bluetooth 非対応のブラウザです（Chrome / Edge を使ってください）");
    }
    const filters = NAME_PREFIXES.map((namePrefix) => ({ namePrefix }));
    const options: RequestDeviceOptions = acceptAll
      ? { acceptAllDevices: true, optionalServices: [SERVICE] }
      : { filters, optionalServices: [SERVICE] };
    const device = await navigator.bluetooth.requestDevice(options);
    this.device = device;
    device.addEventListener("gattserverdisconnected", () => {
      this.writeChar = this.replyChar = this.eventChar = undefined;
    });
    return device.name ?? "(no name)";
  }

  /** Reuse a device that was already granted in an earlier session. */
  async useRemembered(): Promise<string | null> {
    if (!isSupported() || !navigator.bluetooth.getDevices) return null;
    const devices = await navigator.bluetooth.getDevices();
    const match = devices.find((d) => NAME_PREFIXES.some((p) => (d.name ?? "").startsWith(p))) ?? devices[0];
    if (!match) return null;
    this.device = match;
    match.addEventListener("gattserverdisconnected", () => {
      this.writeChar = this.replyChar = this.eventChar = undefined;
    });
    return match.name ?? "(no name)";
  }

  async connect(step: Step = () => {}): Promise<void> {
    const device = this.device;
    if (!device?.gatt) throw new Error("先にデバイスを選択してください");

    step(`GATT に接続: ${device.name ?? "(no name)"}`);
    let lastError: unknown;
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        await device.gatt.connect();
        lastError = undefined;
        break;
      } catch (err) {
        lastError = err;
        step(`接続失敗 (${attempt}/3): ${describeError(err)}`);
        await sleep(700);
      }
    }
    if (lastError) throw new Error(describeError(lastError));

    step("サービス ff00 を取得");
    let service: BluetoothRemoteGATTService | undefined;
    for (let attempt = 1; attempt <= 3 && !service; attempt++) {
      try {
        service = await device.gatt.getPrimaryService(SERVICE);
      } catch (err) {
        lastError = err;
        step(`ff00 が見つかりません (${attempt}/3)`);
        await sleep(500);
      }
    }
    if (!service) {
      throw new Error(
        "ff00 サービスが見つかりません。別のデバイスを選んだ可能性があります" +
          (lastError ? `（${describeError(lastError)}）` : ""),
      );
    }

    this.writeChar = await service.getCharacteristic(CH_WRITE);
    this.replyChar = await service.getCharacteristic(CH_REPLY);
    this.eventChar = await service.getCharacteristic(CH_EVENT);
    step(`特性: write=${this.writeChar.properties.writeWithoutResponse ? "no-response" : "with-response"}`);

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
        this.creditWaiters.shift()?.();
      }
    });
    step("通知を購読しました");
  }

  private wakeReply(): void {
    this.replyWaiters.shift()?.();
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
    if (!char) throw new Error("接続されていません");
    const view = chunk as unknown as BufferSource;
    if (char.properties.writeWithoutResponse) {
      await char.writeValueWithoutResponse(view);
    } else {
      await char.writeValueWithResponse(view);
    }
  }

  async send(stream: Uint8Array, onProgress?: (sent: number, total: number) => void): Promise<number> {
    const total = stream.length;
    const started = performance.now();
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
    // let the printer's UART buffer drain before we report progress
    const deadline = performance.now() + 5000;
    while (outstanding > 0 && performance.now() < deadline) {
      await Promise.race([this.waitCredit(), sleep(250)]);
      outstanding -= 1;
    }
    return (performance.now() - started) / 1000;
  }

  /** Poll 0x70 until it reports twice in a row that it is idle. */
  async waitIdle(timeoutMs = 60000, step: Step = () => {}): Promise<number | null> {
    const deadline = performance.now() + timeoutMs;
    let idle = 0;
    let code: number | null = null;
    while (performance.now() < deadline) {
      const status = await this.query(0x70);
      code = status && status.length > 3 ? status[3] : code;
      if (code === 0x00) {
        idle += 1;
        if (idle >= 2) {
          step("プリンタはアイドル（0x00）");
          return 0x00;
        }
      } else {
        idle = 0;
      }
      await sleep(500);
    }
    step(`タイムアウト: 最後の状態 0x${(code ?? 0xff).toString(16).toUpperCase()}`);
    return code;
  }

  async query(type: number, timeoutMs = 2000): Promise<Uint8Array | null> {
    if (!this.writeChar) throw new Error("接続されていません");
    this.replies = [];
    const frame = mgmtFrame(type) as unknown as BufferSource;
    await this.writeChar.writeValueWithResponse(frame);
    const deadline = performance.now() + timeoutMs;
    while (performance.now() < deadline) {
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

  /** Ask the printer who it is — proves the whole protocol path works. */
  async selfTest(step: Step = () => {}): Promise<{ name: string; status: string; paper: string }> {
    const nameReply = await this.query(0x79);
    const decoder = new TextDecoder("shift_jis");
    const name = nameReply
      ? decoder.decode(nameReply.subarray(3)).replace(/\0.*$/, "")
      : "(no reply)";
    step(`0x79 デバイス名: ${name}`);
    const status = await this.query(0x70);
    step(`0x70 状態: ${status ? `0x${status[3].toString(16).toUpperCase().padStart(2, "0")}` : "(no reply)"}`);
    const paper = await this.query(0x42);
    step(`0x42 用紙: ${paper ? `0x${paper[3].toString(16).toUpperCase().padStart(2, "0")}` : "(no reply)"}`);
    return {
      name,
      status: status && status.length > 3 ? `0x${status[3].toString(16).toUpperCase().padStart(2, "0")}` : "?",
      paper: paper && paper.length > 3 ? `0x${paper[3].toString(16).toUpperCase().padStart(2, "0")}` : "?",
    };
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

export { describeError };
