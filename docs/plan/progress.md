# 進捗

このファイルは、完了した作業、確認したこと、残っている注意点を共有するための場所です。

## 現在の進捗サマリー

基本機能は一通り動作する状態。テキスト → 効果音生成 → 再生・保存・永続化まで通っている。

## 完了済み

### 環境・基盤
- プロジェクト内蔵 Python 3.10.20（`runtime/`）+ `.venv`（システム非依存）
- PyTorch 2.7.1 **cu128**（Blackwell GPU 認識・CUDA 有効）
- stable-audio-tools 0.0.20 + FastAPI/uvicorn + soundfile / PyWavelets / pytorch_lightning
- モデル配置：`models/stable-audio-3-medium/`（重み + config + t5gemma 一式）

### バックエンド（`backend/`）
- **複数モデル対応**：medium / small-sfx を切替可能。選択は `data/config.json` に永続化し次回も使用。`engine.py` が要求モデルをロード（別モデルが載っていれば解放してから差し替え）。t5gemma は1つを共有（複製不要）。`/api/models` `/api/model`
- `engine.py`：モデルの遅延ロード + `generate()`、ローカル（共有）t5gemma を参照
- `server.py`：FastAPI、生成キュー（単一ワーカー）、`/api/generate` `/api/jobs` `/api/audio` `/api/health`
- ジョブの永続化（`data/jobs.json`、起動時復元）
- seed=-1（ランダム）時に実際の seed 値を記録・返却
- カード削除時に `data/` の WAV も削除

### フロントエンド（`frontend/`）
- Electron + React + Vite、Electron が Python サーバを自動起動
- UI：条件入力 → 生成キュー → 結果カード一覧（SUNO 風の横長リスト）
- 自前のオーディオプレーヤー（再生/一時停止・時間・ミュート）＋ **波形ビジュアライザ**（Web Audio で WAV をデコードし canvas 描画、再生済み部分を塗り分け、クリック/ドラッグでシーク）
- 生成条件をグループ化、シンプルなスライダー（値ボックス）、項目名ホバーでヘルプ
- プロンプト欄の自動拡張 + サイドバー幅連動
- カードの `⋮` メニュー：フォームにコピー / ダウンロード / 削除
- デフォルトメニュー非表示、フォーカスのオレンジ枠除去、細いスクロールバー
- ウィンドウサイズ 1600×900

### 起動・ドキュメント
- `start.bat`（ビルド版アプリ）/ `dev.bat`（開発・ホットリロード）
- README.md / CLAUDE.md / .gitignore 整備

## 確認済みのこと
- 生成パイプライン疎通（5 秒の効果音を約 2 秒で生成、WAV 出力）
- アプリ全体起動（Electron + 自動 Python 起動 + UI ポーリング）
- 永続化：再起動後にカード復元・音声再生可
- `ELECTRON_RUN_AS_NODE=1`（VS Code 由来）対策のランチャー（`electron/launch.cjs`）

## 残っている注意点
- Windows に triton が無いため flex_attention は eager フォールバック（動作は問題なし／高速化は今後）
- ジョブ一覧はファイル永続化のみ（DB ではない）。大量生成時の性能は未検証
- `data/` のクリーンアップは慎重に（過去に手動削除で生成物を失った事故あり → 削除前確認を徹底）
- 配布（electron-builder）は未対応。`runtime/` `models/` が巨大なため方式要検討

## 次の一手（候補）
- [plan.md](plan.md) の「今後の候補」を参照
