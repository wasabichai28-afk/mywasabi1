# わさびの薬膳辞書

Streamlitで動作する、食材検索・症状別養生・薬膳レシピのアプリです。

## Streamlit Community Cloudで公開する

1. このリポジトリをGitHubにpushします。アプリの変更とCSVの変更も公開する場合は、それらを含むコミットをpushしてください。
2. [Streamlit Community Cloud](https://share.streamlit.io/) にGitHubアカウントでサインインします。
3. **Create app** を選び、Repositoryに `wasabichai28-afk/mywasabi1`、Branchに `main`、Main file pathに `app.py` を指定してデプロイします。
4. 以後、`main` ブランチへのpushでアプリが更新されます。

依存パッケージはルートの `requirements.txt` からインストールされます。CSVは `app.py` と同じリポジトリルートに置いてください。

## 公開時の注意

このリポジトリはPublicです。pushしたソースコードとCSVは誰でも閲覧できます。アプリはAIを活用して整理した一般情報を掲載しており、医療上の助言や診断・治療を目的とするものではありません。

Streamlit Community Cloudでは、利用状況によりアプリが休止状態になることがあります。公開URLは利用できますが、常時稼働や特定の稼働率が保証されるサービスではありません。
