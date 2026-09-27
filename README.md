# HOANBOY Tracker

診所體脂量測歸檔與追蹤專案。第一版：區網直讀、人工歸檔、離線完整報告與獨立追蹤頁。

- [已確認 MVP 與驗收](docs/mvp-boundary.md)
- [綜合實作規格（待發布）](docs/spec.md)
- [用語](CONTEXT.md)
- [決策紀錄](docs/adr/)
- [設備介接初驗與欄位映射](docs/device-validation.md)
- [完整報告範本與十區映射](docs/report-template-mapping.md)
- [有值報告核對與來源缺口](docs/report-filled-validation.md)

目前進行唯讀介接驗證，尚無可用應用程式。
病患資料、設備回應與報告樣本僅置於忽略版控的 `private/`；此目錄仍含敏感資料，Git 忽略不等於加密或存取控制。

## 唯讀驗證

在專案根目錄執行 `./scripts/Read-DeviceSnapshot.ps1`，讀取指定設備的 bodyparm，產生獨立的本機快照與不含個別值的欄位統計。需 Windows PowerShell 與 curl.exe；不是排程同步服務。
