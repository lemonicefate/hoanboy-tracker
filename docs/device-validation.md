# 設備介接初驗 — 2026-09-27

## 結論

已從指定設備端點唯讀取得 bodyparm；可進行匯入設計，但尚未證實新量測及重啟後的持續可讀性，也未完成完整報告對照。

## 證據

- 來源：192.168.1.102:8080，heer_scale.db / bodyparm。
- 讀取頁面與 app.js 確認官方頁面本身採用 getTableList?database=heer_scale.db 後呼叫 getAllDataFromTheTable?tableName=bodyparm；這是設備除錯介面的實際行為，不代表廠商支援契約。
- 14 列、152 欄；每列寬度與 schema 相符，沒有完全重複列。
- uid 被 schema 標記為主鍵；本次 14 筆全部有值且唯一。尚未驗證設備清庫或重啟後是否重用。
- time 14 筆有值且唯一；目前唯一不代表可作永久去重鍵。
- username 14 筆有值、9 個不同值，其中 11 筆符合 `09` 開頭十碼或 +886 手機格式，3 筆不符合。是手機候選欄位，尚不能推定全部資料皆以手機填寫。
- userUid 14 筆有值、9 個不同值，為 integer；屬設備端使用者識別候選，不當作病歷號。
- parameter、result 全空；其餘 150 欄在本次樣本均有值，但有值不等於有效或與雲端一致。
- weight 與 bhWeightKg 最大絕對差約 0.000003，符合微小浮點差異；此處不藉此宣稱所有欄位已核對。
- 兩次緊接的讀取 SHA-256 相同；只能證明本次靜態快照一致，不能證明新量測更新或重啟穩定性。

原始快照：private/bodyparm.json、private/bodyparm-repeat.json；欄位統計：private/profile/columns.csv。上述不進 Git，不輸出個別病人值。
可重跑檢查：scripts/Inspect-DeviceSnapshot.ps1。可取得新快照：scripts/Read-DeviceSnapshot.ps1。

## 初步映射（全部待原廠報告核對）

| 用途 | 候選來源 | 處理限制 |
|---|---|---|
| 來源量測 ID | uid | 需加入設備識別；重用及變更語義待驗證 |
| 來源手機 | username | 保留原字串，非手機格式不得強制轉換 |
| 來源使用者 | userUid | 不等同診所病人 |
| 量測時間 | time | 時間格式與時區仍需實證 |
| 原始輸入 | age / birthday / gender / height / weight | 性別代碼與單位待核對 |
| 體重、BMI、體脂率 | bhWeightKg / bhBMI / bhBodyFatRate | 數值以 text 傳回；不可直接當已驗證的單位 |
| 身體組成 | bhWaterKg / bhProteinKg / bhMineralKg / bhBodyFatKg / bhBodyFatFreeMassKg | 對照報告標籤、單位及精度 |
| 肌肉 | bhMuscleKg / bhSkeletalMuscleKg | 兩者不可混用 |
| 評分及其他 | bhBodyScore / bhBodyAge / bhBMR / bhVFAL / bhWHR | 量綱與原廠語義待核對 |
| 分段分析 | bhBodyFatKg* / bhBodyFatRate* / bhMuscleKg* | 躯幹、左右臂腿順序需逐區塊核對 |
| 參考範圍與等級 | *ListMin / *ListMax / *Level | 保存來源，不自建原廠等級或參考區間 |
| 阻抗 | bhZ20Khz* / bhZ100Khz* | EnCode 與 DeCode 意義待核對 |

## 實作約束

- 頁面先選資料庫再讀表，讀表 URL 不帶 database；可能有伺服器共享選庫狀態。後端需序列化自己的讀取，並驗證回應 schema；並行瀏覽器切換資料庫風險仍待確認。
- Windows PowerShell Invoke-WebRequest 本次報 ResponseStatusLine 協定錯誤；curl.exe 直連成功。尚未定位是代理路徑或 HTTP 相容性，採 curl.exe --noproxy '*' 作驗證工具。
- 尚無可用應用程式，尚未限制設備防火牆，不可視為可正式上線。

## 下一個必要證據

### 新量測驗證進展

2026-09-27 使用者完成測試量測後再次唯讀抓取：由 14 筆增加為 15 筆，新增一個 uid。使用者提供的測試手機輸入在 username 欄精確匹配一筆，且即為新增列。這確認本次「輸入識別 → username → 新增量測」流程可讀，不代表所有歷史 username 都是有效手機，也不代表重測與重啟語義已驗證。

比對摘要保存在 private/reference/new-measurement-check.json；個別識別、量測值不納入版控。該列 time 沒有時區標記，仍按设备原始時間保存，不宣稱已完成時鐘及時區校準。下一步可直接用這次測試報告核對數值及代碼。

1. 已檢視空白及有值照片，完成[十區版面與候選欄位映射](report-template-mapping.md)及[有值報告核對](report-filled-validation.md)。有值報告不在目前 14 筆設備量測中，因此同次數值、代碼與單位驗證仍待補證據；分段標準判定亦無直接來源。
2. 新量測前後快照已確認新增一筆與測試識別相符；重測行為、設備時間校準及同次完整報告對照仍待驗證。
3. 在不影響診間作業的時間由人員重啟設備後重讀，核對介面可用與識別持續性。

不遠端重啟設備、不修改設備資料、不呼叫雲端計算服務。
