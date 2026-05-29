# CLAUDE.md

このリポジトリで作業する Claude / 開発者向けの技術メモ。ユーザー向けの使い方は [README.md](README.md) を参照。

## プロジェクト概要

Stable Audio 3 Medium をローカル実行し、テキストから効果音を生成するデスクトップアプリ。
Python バックエンド（推論）と Electron + React フロントエンド（UI）を、ローカル HTTP API で接続する構成。

## アーキテクチャ

```
Electron (renderer/React)  --HTTP-->  FastAPI (backend/server.py)  -->  engine.py  -->  stable-audio-tools / PyTorch (CUDA)
        ^ frontend/src              ^ 127.0.0.1:8765                      ^ モデルロード+生成
        |
   Electron main (frontend/electron/main.cjs) が .venv の Python で server.py を spawn
```

- フロントは `window.__API_BASE__`（preload で注入, 既定 `http://127.0.0.1:8765`）に対して `fetch`。IPC は使っていない。
- 生成は `backend/server.py` 内の単一ワーカースレッド + `queue.Queue` で**1件ずつ順次処理**（GPU が1基のため）。ジョブ状態はメモリ保持、WAV は `data/<job_id>.wav`。
- フロントは 1.5 秒ごとに `/api/jobs` と `/api/health` をポーリングしてカードを更新。

## 重要な環境上の制約

- **Python は 3.10 必須**。`stable-audio-tools==0.0.20` の `requires_python` が `<3.11,>=3.10`。3.11 以降では入らない。
- Python はシステムに入れず、`runtime/python/`（python-build-standalone, 3.10.x）に内蔵し、そこから `.venv` を作成している。
- GPU は Blackwell (sm_120, capability 12.0)。**PyTorch は cu128 ビルドが必須**：
  `pip install torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128`
  通常の PyPI 版（CPU/旧 CUDA）では Blackwell を認識しない。
- `torch==2.7.1+cu128` は stable-audio-tools の `torch==2.7.1` ピン（local version 無視）を満たすため、先に cu128 を入れてから stable-audio-tools を入れると downgrade されない。**この順序を守る。**

### インストール後に必要だった追加対応（ハマりどころ）

1. **PyWavelets**: stable-audio-tools が `PyWavelets==1.4.1`（NumPy 1.x ABI 向けビルド）を固定。NumPy 2.x 環境では `pip install --upgrade "PyWavelets>=1.7"` で上書き必須（pip の依存競合警告は出るが実害なし）。
2. **pytorch_lightning**: `models/lora/callbacks.py` が無条件 import するため別途インストールが必要（推論のみでも）。
3. **soundfile**: Windows の torchaudio は WAV 保存バックエンド（libsndfile）を持たず `torchaudio.save` が失敗する。`engine.py` は `soundfile.write` で保存している。
4. **triton 非搭載 (Windows)**: モデルは `flex_attention` を使い torch.compile で Triton カーネルへ lower しようとするが Windows に triton が無く失敗 → eager フォールバック。`engine.py` で `torch._dynamo.config.suppress_errors = True` を設定し、毎回の大量 traceback を抑制している。速度を上げたい場合は `triton-windows` の導入を検討。
5. **flash_attn 未導入**: 自動で無効化されるだけ（警告のみ、問題なし）。
6. **seed=-1 (ランダム) の int32 バグ**: stable-audio-tools の生成関数は seed が -1 のとき `np.random.randint(0, 2**32 - 1)` を呼ぶが、Windows では NumPy の既定整数が int32 で上限超過 → `ValueError: high is out of bounds for int32`。`engine.py` 側で seed<0 のとき自前で `random.randint(0, 2**31-1)` を選び**必ず明示的に seed を渡す**ことで回避している。

## モデルファイル

- HF リポジトリ `stabilityai/stable-audio-3-medium` は**ゲート付き**（401）。取得には HF 認証 or ログイン済みブラウザでの手動 DL が必要。
- ローカル配置は HF リポジトリ構造をミラーする（`backend/engine.py` の `MODEL_DIR` 以下）。
- `engine.py` の `_patch_text_encoder_paths()` が `model_config.json` 内の t5gemma 参照をローカルフォルダの絶対パスへ書き換え、完全オフラインでロードする。**model_config.json の中身を見て参照キー名が変わっていたらここを調整する。**
- `models/qwen3.5_2b_bf16.safetensors` は medium のロードには未使用（large 用 or プロンプト補助の可能性）。現状ロード対象外。

## 主要ファイル

| ファイル | 役割 |
|---------|------|
| `backend/engine.py` | モデルのロード（遅延・1回のみ）と `generate()`。スレッドロックで直列化。 |
| `backend/server.py` | FastAPI。`/api/generate`(POST), `/api/jobs`, `/api/jobs/{id}`(GET/DELETE), `/api/audio/{id}`, `/api/health`。ワーカースレッドでキュー処理。 |
| `frontend/electron/main.cjs` | Python サーバ spawn → `/api/health` を待機 → BrowserWindow 生成。終了時に Python を kill。 |
| `frontend/src/App.jsx` | ポーリング・状態管理・レイアウト。 |
| `frontend/src/components/GenerateForm.jsx` | プロンプト・パラメータ入力、プリセット。 |
| `frontend/src/components/ResultCard.jsx` | ジョブ1件のカード（状態・再生・保存・削除）。 |

## 実行・デバッグ

```powershell
# フル起動（Vite + Electron + 自動で Python サーバ）
cd frontend; npm run dev

# バックエンド単体（推論デバッグ用）
.venv\Scripts\python.exe backend\server.py --port 8765

# import 疎通の最小確認
.venv\Scripts\python.exe -c "import torch,stable_audio_tools; print(torch.cuda.is_available())"
```

## 生成パラメータの既定

- steps=8, cfg_scale=1.0, sampler="pingpong"（SA3 は 8 step 程度で生成可能なように後段学習済み）。
- `engine.generate()` は要求秒数をモデルの `sample_size/sample_rate` 上限にクランプする。
- CUDA 時は model を fp16 にしている（48GB なら fp32 でも可。VRAM/速度に応じて調整）。

## 注意点 / TODO 候補

- ジョブ状態はメモリのみ。アプリ再起動で一覧は消える（WAV ファイルは残る）。永続化するなら SQLite/JSON に。
- `generate_diffusion_cond_inpaint` を素の条件生成に流用している。挙動に問題があれば `generate_diffusion_cond` へ切替（engine.py 内で try/except 済み）。
- 配布（electron-builder）時は `runtime/` `.venv/` `models/` を同梱するか別途 DL させるか要検討（巨大）。
