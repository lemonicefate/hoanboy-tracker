# HOANBOY Tracker

診所體脂量測歸檔與追蹤專案。第一版：區網直讀、人工歸檔、離線完整報告與獨立追蹤頁。

- [已確認 MVP 與驗收](docs/mvp-boundary.md)
- [綜合實作規格](docs/spec.md)
- [用語](CONTEXT.md)
- [決策紀錄](docs/adr/)
- [設備介接初驗與欄位映射](docs/device-validation.md)
- [完整報告範本與十區映射](docs/report-template-mapping.md)
- [有值報告核對與來源缺口](docs/report-filled-validation.md)

已實作本機工作台：登入、區網唯讀同步、病人與人工歸檔、歷史與追蹤、保存報告核對稿、備份及隔離還原。**完整報告尚未驗收，不能作正式臨床報告。** 原廠代碼、節段判定與數值核對缺口仍保留，詳見 [實作與驗收狀態](docs/implementation-status.md)。
病患資料、設備回應與報告樣本僅置於忽略版控的 `private/`；此目錄仍含敏感資料，Git 忽略不等於加密或存取控制。

## 唯讀驗證

在專案根目錄執行 `./scripts/Read-DeviceSnapshot.ps1`，讀取指定設備的 bodyparm，產生獨立的本機快照與不含個別值的欄位統計。需 Windows PowerShell 與 curl.exe；不是排程同步服務。

## 啟動（Windows）

在專案資料夾執行，需已安裝 `uv`：

```powershell
uv sync --frozen
uv run python -m hoanboy init
uv run python -m hoanboy serve
```

`init` 會要求輸入至少 12 字元的操作密碼，不提供預設密碼。開啟 **http://127.0.0.1:8765**。只監聽本機；同一資料目錄禁止同時啟動第二個程式。也可執行 `./scripts/Start-Tracker.ps1`（首次會初始化）。

1. 按「同步設備」；來源預設 `192.168.1.102:8080`、`heer_scale.db/bodyparm`。不寫入或重啟設備。
2. 在「病人與追蹤」建立病人，再從待歸檔逐筆核對及選人。手機提示不會自動歸檔。
3. 病人頁查看歷史；未核對的數值不進正式曲線。量測明細保留來源、缺值、原始輸入及歸檔事件。
4. 已歸檔量測可保存／查看十區**報告核對稿**，按 Ctrl+P 列印。模板與資料一同保存在 SQLite，重印不需設備或網際網路。

## 設定與備份

停止程式後編輯 `private/app/config.json`。`device_address` 為設備 IP、`device_id` 為穩定設備識別；更換設備時使用新的識別。正式使用前將 `backup_dir` 設成另一儲存裝置的絕對路徑，並限制 Windows 資料目錄權限及設備除錯介面的可存取主機。不要對外開放設備或本機服務。

主程式的設備 IP 可更改，重啟後生效；設備 port 目前固定 `8080`。舊唯讀驗證腳本 `Read-DeviceSnapshot.ps1` 另有限制，只接受原本的設備 IP，不會讀取應用設定。發布前檢查範圍與結果見 [敏感資料檢查](docs/privacy-review.md)。

`verified_fields` 預設空白。只有取得同次來源與報告的欄位／單位核對證據後，才可填入來源欄名與本機證據索引；不能為了顯示曲線自行設為已驗證。核對狀態隨匯入版本保存，修改設定不會自動回寫已保存量測。重啟後，可在量測明細按「套用目前已核對欄位設定」，明確建立新的核對版本；原始資料、舊核對版本及已保存報告均保留。之後產生報告會使用新核對版本，舊報告仍可由明細頁查阅。體型、Level、節段與長條規則尚無已驗證實作，所有報告仍為核對稿。

每次資料變更後更新當日備份，保留 30 個使用日；手動備份不自動刪除。資料庫含病人、來源列與 schema、歸檔事件、報告 HTML 與內嵌樣式。備份失敗會顯示警告，原本的資料保存仍有效。

在「備份與還原」先選「隔離還原並驗證」。頁面提供還原 ID；停止程式後執行：

```powershell
uv run python -m hoanboy restore <還原ID>
uv run python -m hoanboy serve
```

啟用前重新核對 SHA-256 與 SQLite 完整性，先備份目前資料，再替換資料庫並使舊登入失效。密碼與設備設定維持本機現況。還原不可在服務執行中進行。

自訂資料目錄：所有指令將 `--data-dir C:/指定路徑` 放在 `init`、`serve` 或 `restore` **之前**。應用停止後可連同 `config.json` 保存整個私有資料目錄；不要放入 Git。跨電腦災難復原時，先初始化新目錄，再將備份 `.sqlite3` 與同名 `.json` 校驗檔放到設定的備份目錄，從隔離還原流程操作。

## 開發驗證

```powershell
uv sync --frozen
uv run playwright install chromium
uv run mypy
node --check hoanboy/static/app.js
uv run pytest -q
```

測試只使用虛構資料。主要 seam 是本機 HTTP API，搭配真實暫存 SQLite；瀏覽器測試覆蓋登入、同步、歸檔、離線重印、A4 單頁與還原。`test-results/` 產生虛構截圖、PDF 和效能結果，不進 Git。
