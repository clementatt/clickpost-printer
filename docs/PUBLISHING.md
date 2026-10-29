# 公開・リリースの手順

## すでにできていること

| 対象 | 場所 | 更新方法 |
|---|---|---|
| GitHub リポジトリ | https://github.com/clementatt/clickpost-printer | `git push origin main` |
| デモサイト | https://clickpost.l-l.li/ （Cloudflare Workers の静的アセット） | `cd web && npm run build && npx wrangler deploy` |
| GitHub Release | https://github.com/clementatt/clickpost-printer/releases | `git tag v0.1.1 && git push origin v0.1.1` |

タグを push すると `.github/workflows/release.yml` が走り、次を添付した Release を作ります。

- `clickpost_printer-<version>-py3-none-any.whl`
- `clickpost_printer-<version>.tar.gz`
- `web-dist.zip`（`web/dist` を丸ごと。Workers / Pages / 社内サーバーどこでも置ける）

## PyPI だけは初回の設定が必要

PyPI への公開は **trusted publishing**（OIDC、トークン不要）で行う構成にしてありますが、
PyPI 側に「どのリポジトリのどの workflow を信頼するか」を一度だけ登録する必要があります。

1. https://pypi.org/manage/account/publishing/ を開く
2. **Add a new pending publisher** を選び、次のとおり入力する

   | 項目 | 値 |
   |---|---|
   | PyPI Project Name | `clickpost-printer` |
   | Owner | `clementatt` |
   | Repository name | `clickpost-printer` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

3. 登録できたら、新しいタグを push する（または GitHub の Actions から release を再実行）

   ```bash
   git tag v0.1.1 && git push origin v0.1.1
   ```

   以後はこれだけで PyPI に上がります:

   ```bash
   pip install 'clickpost-printer[ble]'
   ```

### token を使う場合（trusted publishing を設定しないとき）

```bash
python -m build
python -m twine upload dist/*        # username: __token__ / password: pypi-... のトークン
```

## デモサイトの設定

- ホスト: Cloudflare Workers（静的アセットのみ、サーバーサイドコードなし）
- ドメイン: `clickpost.l-l.li`（`l-l.li` ゾーンの custom domain）
- 設定: [`web/wrangler.jsonc`](../web/wrangler.jsonc)
- 詳細: [DEPLOY.md](DEPLOY.md)

デモは「PDF はどこにも送られない」ことを売りにしているので、アクセス解析や
サーバーログ収集は入れていません。入れる場合はプライバシー表記も更新してください。
