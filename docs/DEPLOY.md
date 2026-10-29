# Web 版を Cloudflare Workers に置く

Web 版は**完全な静的サイト**です。PDF の解析・切り出し・ビットマップ化・BLE 送信は
すべて閲覧者のブラウザの中で起きるので、サーバー側のコードもストレージも要りません。
Cloudflare 側に置くのは `web/dist/` の静的ファイルだけです。

## なぜ「Workers で印刷」ではないのか

Cloudflare Workers は V8 isolate で動くので、**USB も Bluetooth も触れません**。
PDF → 300 dpi ビットマップのラスタライズも（MuPDF 相当が無いため）現実的ではありません。
そこで役割を分けています。

| 層 | 担当 |
|---|---|
| Cloudflare Workers | 静的ファイルの配信（HTML / JS / pdf.js / CMaps / サンプル PDF）だけ |
| ブラウザ | PDF 解析・ラベル検出・ラスタライズ・二値化・命令列の生成 |
| Web Bluetooth | プリンタへ 512 バイトずつ転送（クレジットによるフロー制御） |

つまり運単（氏名・住所）は**一度もネットワークに出ません**。

## デプロイ

```bash
cd web
npm install
npm run build          # -> web/dist（pdf.js の CMaps / 標準フォントも同梱）
npx wrangler login     # 初回のみ
npx wrangler deploy
```

`web/wrangler.jsonc` の `assets.directory` が `./dist` を指しているので、
ビルド済みの静的ファイルがそのまま配信されます。出力例:

```
https://clickpost-printer.<your-subdomain>.workers.dev
```

カスタムドメインは `wrangler.jsonc` に追記するか、ダッシュボードの
「Workers & Pages → clickpost-printer → Settings → Domains & Routes」から足せます。

```jsonc
{
  "name": "clickpost-printer",
  "compatibility_date": "2026-01-01",
  "assets": { "directory": "./dist", "not_found_handling": "single-page-application" },
  "routes": [{ "pattern": "label.example.com", "custom_domain": true }]
}
```

Cloudflare Pages でも同じ `dist` をそのまま公開できます（`Build command: npm run build`,
`Output directory: dist`）。ただし `assets` を使う Workers の方が設定が少なく済みます。

## 注意

- Web Bluetooth は **HTTPS 必須**です（`workers.dev` は最初から HTTPS）。
  ローカル確認は `npm run dev` の `http://localhost:5173`（localhost は例外）で。
- 対応ブラウザは **Chrome / Edge（デスクトップ）**。Safari・Firefox は Web Bluetooth 非対応です。
- サーバー側に何も置かないので、アクセス解析も入れていません（入れるなら別途）。

## 将来「どこからでも印刷」をやるなら

Workers に Durable Object のキューを置き、自宅PCで常駐エージェントが
WebSocket でジョブを引いて印刷する構成になります。ただし運単をクラウドに
預けることになるので、このリポジトリでは採用していません。
