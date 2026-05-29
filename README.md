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
└── data/                   # 生成された WAV
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

---

## 動作環境（確認済み）

- Windows 11
- NVIDIA GPU（Blackwell, RTX PRO 5000 / 48GB VRAM で検証）
- CUDA ドライバ（PyTorch cu128 同梱ランタイムを使用）
- Python 3.10（内蔵）、Node.js 24

---

## ライセンス上の注意

Stable Audio 3 Medium のモデル重みは **Stability AI Community License** に従います。商用利用の可否・条件は[モデルカード](https://huggingface.co/stabilityai/stable-audio-3-medium)および同梱の `LICENSE.md` を確認してください。本アプリのコード自体は MIT ライセンスです。
