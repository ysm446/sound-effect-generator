# Sound Effect Generator

[Stable Audio 3 Medium](https://huggingface.co/stabilityai/stable-audio-3-medium) を使って、テキストプロンプトから効果音をローカル生成するデスクトップアプリです。

- **バックエンド**: Python (FastAPI) + [stable-audio-tools](https://pypi.org/project/stable-audio-tools/) + PyTorch (CUDA)
- **フロントエンド**: Electron + React + Vite
- **UI**: 条件を設定 → 生成キューに投入 → 結果をカードとして一覧表示・再生・WAV保存

すべてプロジェクトフォルダ内で完結します（Python本体も `runtime/` に内蔵し、システムを汚しません）。

---

## 構成

```
sound-effect-generator/
├── runtime/python/         # プロジェクト内蔵 Python 3.10 (standalone build)
├── .venv/                  # Python 仮想環境（依存パッケージ）
├── models/
│   └── stable-audio-3-medium/
│       ├── model_config.json
│       ├── model.safetensors
│       └── t5gemma-b-b-ul2/        # テキストエンコーダ一式
├── backend/
│   ├── engine.py           # モデルロード + 推論
│   ├── server.py           # FastAPI（生成キュー付き API）
│   └── requirements.txt
├── frontend/
│   ├── electron/           # Electron メインプロセス（Python サーバ自動起動）
│   ├── src/                # React UI
│   ├── package.json
│   └── vite.config.js
├── app-config.json         # ローカル設定（保存先フォルダ・選択モデル）
└── data/                   # 生成された WAV（保存先は変更可能）
```

---

## セットアップ

### 1. モデルファイルの配置

Stable Audio 3 Medium は **ゲート付きリポジトリ**です。Hugging Face でアクセス申請（承認）後、以下を `models/stable-audio-3-medium/` 以下に配置してください。

| ファイル | 配置先 |
|---------|--------|
| `model.safetensors` | `models/stable-audio-3-medium/` |
| `model_config.json` | `models/stable-audio-3-medium/` |
| `t5gemma-b-b-ul2/` フォルダ一式 (config.json, tokenizer 各種, model.safetensors) | `models/stable-audio-3-medium/t5gemma-b-b-ul2/` |

> 不足ファイルがある場合、アプリ上部に「モデルファイルが不足しています」と表示されます。

### 2. Python 環境

プロジェクト内蔵の Python と `.venv` は既にセットアップ済みです。再構築する場合：

```powershell
# 内蔵Pythonからvenvを作成
runtime\python\python.exe -m venv .venv

# PyTorch (Blackwell 向け CUDA 12.8 ビルド)
.venv\Scripts\python.exe -m pip install torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128

# 残りの依存
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### 3. フロントエンド依存

```powershell
cd frontend
npm install
```

---

## 実行

### かんたん起動（バッチファイル）

エクスプローラーからダブルクリックするだけで起動できます。

| ファイル | 用途 |
|---------|------|
| **`start.bat`** | 通常起動。UIを自動ビルドして、アプリ（DevToolsなし）として起動します。普段使いはこちら。 |
| **`dev.bat`** | 開発起動。Vite ホットリロード + DevTools 付き。コードを編集しながら使うとき。 |

どちらも Python バックエンド(8765)を自動起動し、終了時に一緒に停止します。

### 開発モード（ホットリロード）

```powershell
cd frontend
npm run dev
```

Vite 開発サーバー(5173)と Electron が起動し、Electron が Python バックエンド(8765)を自動起動します。

### バックエンド単体で起動（デバッグ用）

```powershell
.venv\Scripts\python.exe backend\server.py --port 8765
# http://127.0.0.1:8765/api/health で状態確認
```

### プロダクションビルド

```powershell
cd frontend
npm run build   # React をビルド
npm start       # Electron で dist を読み込み起動
```

---

## 使い方

1. アプリ左の **生成条件** パネルでプロンプト（英語推奨）・長さ・ステップ数・CFG・シードを設定
2. **「＋ 生成キューに追加」** をクリック
3. 右の **生成結果** パネルにカードが追加され、生成が完了すると再生・WAV保存が可能になります

生成は GPU 1基につき 1件ずつ順番に処理されます（キュー方式）。

### 保存先フォルダを変える

生成した WAV と結果一覧（`jobs.json`）の保存先は、左パネルの **保存先フォルダ** で変更できます（既定はプロジェクト内の `data/`）。アプリ本体と生成データを別ドライブに分けたい場合に使います。

- 「参照…」でフォルダを選ぶと、以降の生成はそのフォルダに保存されます（設定は `app-config.json` に記録され、次回起動時も維持されます）
- 切り替えは**選んだフォルダを読み込むだけ**で、ファイルの移動・コピー・削除は行いません。既存の結果を持ち込みたい場合は、フォルダの中身（`*.wav` と `jobs.json`）を手動でコピーしてください
- 生成中・待機中のジョブがあるときは変更できません
- 設定したフォルダが見つからない場合（外付けドライブ未接続など）は、`data/` にフォールバックして起動します

### コマンドライン／LLM から使う（CLI・MCP）

UI を開かずに生成できる入口を用意しています。どちらも UI と同じバックエンド（`127.0.0.1:8765`）を使い、**動いていなければ裏で自動起動**します。起動したバックエンドはそのまま常駐し（モデルのロードを毎回払わないため）、**10 分間なにも要求がなければ自動で終了**します（`SFX_IDLE_TIMEOUT` 秒で変更、0 で無効）。すぐ落としたいときは `sfx stop`。アプリ（Electron）が起動したバックエンドは対象外で、従来どおりアプリ終了時に止まります。生成結果は UI と同じ保存先フォルダに入り、アプリを開けばカードとしても見えます。

#### CLI（`sfx.bat`）

```powershell
.\sfx.bat generate "glass shattering on a tile floor" --seconds 4   # WAV のパスを標準出力に出す
.\sfx.bat generate "door creak" --seconds 3 --seed 42 --json       # 結果をまるごと JSON で
.\sfx.bat list --limit 5        # 最近の結果
.\sfx.bat get <job_id>          # 1件の詳細
.\sfx.bat status                # バックエンドが動いているか
.\sfx.bat start / stop          # バックエンドの起動／終了
```

- オプション：`--seconds` `--steps` `--cfg-scale` `--negative` `--seed`（-1 でランダム）`--timeout`
- 進捗はstderr、結果はstdoutに出るので、スクリプトからは `--json` でstdoutだけを読めば十分です
- 別ポートで動かす場合は環境変数 `SFX_PORT`（既定 8765）
- 自動起動したバックエンドのログは `cli-server.log`（プロジェクト直下）
- 自動終了までの時間は環境変数 `SFX_IDLE_TIMEOUT`（秒、既定 600）。アプリの UI を開いている間はポーリングが活動と見なされるので落ちません

#### MCP サーバー（Claude Code / Claude Desktop などから）

`backend/mcp_server.py` が MCP（Model Context Protocol）サーバーとして次のツールを公開します。LLM に「〜の効果音を作って」と頼むと、裏でバックエンドを立ち上げて生成し、WAV のパスが返ります。

| ツール | 役割 |
|-------|------|
| `generate_sound_effect(prompt, seconds, steps, cfg_scale, negative_prompt, seed)` | 生成して WAV の絶対パスと使用 seed を返す（完了まで待つ） |
| `list_sound_effects(limit)` | 最近の結果一覧 |
| `backend_status()` | バックエンドの状態 |
| `stop_backend()` | バックエンド終了（VRAM 解放） |

- **Claude Code**：プロジェクト直下の `.mcp.json` に登録済み。このフォルダで `claude` を起動すれば `sfx` サーバーとして使えます（初回は承認ダイアログが出ます）。手動登録する場合：
  ```powershell
  claude mcp add sfx -- .venv/Scripts/python.exe backend/mcp_server.py
  ```
- **Claude Desktop** など他のクライアント：`command` に `<プロジェクト>\.venv\Scripts\python.exe`、`args` に `<プロジェクト>\backend\mcp_server.py` を絶対パスで指定してください
- 初回呼び出しはバックエンド起動＋モデルロードで 1 分弱かかることがあります。2 回目以降は数秒です

#### 他のプロジェクトから使う（ゲーム・動画などの作業中に効果音を作らせる）

`.mcp.json` はこのフォルダで `claude` を起動したときだけ有効です。別のプロジェクトの作業中に LLM に効果音を作らせるには、次の 2 つを行います。

**1. ユーザー設定として登録する（一度だけ）**

どのフォルダから起動しても `sfx` ツールが見えるようになります。絶対パスで指定してください（この例はプロジェクトが `D:\GitHub\sound-effect-generator` にある場合）。

```powershell
claude mcp add --scope user sfx -- D:\GitHub\sound-effect-generator\.venv\Scripts\python.exe D:\GitHub\sound-effect-generator\backend\mcp_server.py
claude mcp list   # 「sfx: ... ✓ Connected」と出れば OK
```

**2. 相手プロジェクトの `CLAUDE.md`（または `AGENTS.md`）に使い方を書く**

ツールが見えていても、LLM はそれをいつ・どう使うかを知りません。以下をそのままコピーして貼ってください。使う保存先フォルダ名などは自分の環境に合わせて直します。

````markdown
## 効果音の生成（sfx MCP）

このマシンには Stable Audio 3 をローカル実行する効果音ジェネレーターがあり、
MCP サーバー `sfx` のツールとして使える。効果音（SE）が必要になったら
自分で生成してよい。

- `generate_sound_effect(prompt, seconds=8, steps=8, cfg_scale=1.0, negative_prompt=None, seed=-1)`
  生成が終わるまで待ち、WAV の絶対パスと実際に使った seed を返す。
  初回はバックエンド起動とモデルロードで 1 分弱かかる。2 回目以降は数秒。
- `list_sound_effects(limit)` 最近生成したものと WAV パスの一覧
- `backend_status()` / `stop_backend()` 状態確認と即時終了。
  バックエンドは 10 分使われなければ自動で終了するので、通常は呼ばなくてよい。
  すぐ VRAM を空けたいときだけ `stop_backend()` を呼ぶ。

### プロンプトの書き方
- **英語**で書く。日本語の依頼は英語に訳してから渡す。
- 音そのものを具体的に描く：素材・動作・空間・距離。
  良い例: "heavy wooden door slamming shut in a stone hallway, close mic"
  悪い例: "door sound", "scary noise"
- 音楽・声・歌詞は不得意。効果音・環境音・アンビエンスに使う。
- 長さは必要最小限にする（ワンショットは 1〜3 秒、ループ素材やアンビエンスは 8〜20 秒）。
  上限は約 47 秒。
- 同じ音のバリエーションが欲しいときは prompt を固定して `seed` だけ変える。
  気に入った結果を再現するには返ってきた seed を渡す。
- 品質に不満があれば `steps` を 16〜32 に上げる（生成時間は比例して増える）。

### 生成後にやること
- 返ってきた WAV パスのファイルを、このプロジェクトのアセットフォルダ
  （例: `assets/sfx/`）に **コピー**して、用途が分かる名前に変える。
  元ファイルはジェネレーター側の保存先に残るので、移動や削除はしない。
- 生成した音が要望と違ったら、プロンプトを具体化して再生成する。
  最初から複数案（seed 違いで 2〜3 個）を作って選ばせてもよい。
- 形式は 44.1 kHz ステレオ WAV。別の形式やモノラルが必要なら ffmpeg 等で変換する。
````

**MCP を使わない場合（CLI）**

MCP を登録できない環境や、スクリプトから呼びたい場合は CLI でも同じことができます。LLM には次を伝えてください。

```markdown
効果音は次のコマンドで生成できる（WAV の絶対パスが標準出力に出る）:
  D:\GitHub\sound-effect-generator\sfx.bat generate "<english prompt>" --seconds 3
`--json` を付けると結果全体（seed 含む）が JSON で返る。
```

---

## 動作環境（確認済み）

- Windows 11
- NVIDIA GPU（Blackwell, RTX PRO 5000 / 48GB VRAM で検証）
- CUDA ドライバ（PyTorch cu128 同梱ランタイムを使用）
- Python 3.10（内蔵）、Node.js 24

---

## ライセンス上の注意

Stable Audio 3 Medium のモデル重みは **Stability AI Community License** に従います。商用利用の可否・条件は[モデルカード](https://huggingface.co/stabilityai/stable-audio-3-medium)および同梱の `LICENSE.md` を確認してください。本アプリのコード自体は MIT ライセンスです。
