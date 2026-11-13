# self-host-agent

用 Claude Managed Agents 的「自行託管的沙箱」（self-hosted sandboxes）做的進貨發票對帳範例，
沙箱是一台 Proxmox（PVE）上的 Linux VM。

這份 README 分兩部分：先講清楚這個東西是什麼，再一步一步照著架起來。

官方文件：

- [自行託管的沙箱](https://platform.claude.com/docs/zh-TW/managed-agents/self-hosted-sandboxes)
- [選擇代理環境](https://platform.claude.com/docs/zh-TW/managed-agents/choosing-an-environment)

## 這是什麼

一個 agent 由三個元件組成：

| 元件 | 做什麼 |
|---|---|
| LLM | 模型。輸入文字、輸出文字。它不會執行任何東西，最多只會輸出「我要呼叫 bash，指令是這個」 |
| Harness | 包在 LLM 外面的程式。呼叫 LLM、解析工具呼叫、把執行結果接回對話、一直重複到做完 |
| Sandbox | 工具呼叫實際執行的地方。Agent 碰得到什麼檔案和網路，由它決定 |

各種做法只是這三個元件放的位置不同：

| 做法 | LLM | Harness | Sandbox |
|---|---|---|---|
| Claude Code | 雲端 | 你的電腦 | 你的電腦 |
| Managed Agents（預設的雲端環境） | 雲端 | 雲端 | 雲端 |
| **Managed Agents 自行託管的沙箱（本專案）** | 雲端 | 雲端 | **你的機器** |

Harness 在雲端、sandbox 在你的機器，兩者隔著網際網路，所以需要一支叫 **worker** 的程式把它們接起來。
Worker 裝在你的機器上，主動向外連線去領工具呼叫，在本機執行後把結果送回去。它自己不會思考。

### 什麼時候才需要它

官方文件的建議是：不確定就用雲端環境。只有工具必須在你控制的基礎架構上執行時，才選自行託管的沙箱，例如：

- 資料不能整包搬出你的網路。
- Agent 要連外面連不到的內部服務。
- 工具要在你自己設定、記錄、稽核的主機上執行。

### 它不會改變的事

- 對話紀錄和**工具的執行結果仍然會送到 Anthropic**，模型才能看結果、決定下一步。留在你機器上的是檔案本身和執行過程。
- 對話紀錄的保留時間和合規涵蓋範圍，和雲端環境相同。

## 這個範例在做什麼

模擬一家公司的應付帳款流程：供應商寄來 20 張發票，agent 逐張比對 ERP 裡的採購單和驗收紀錄
（三方比對），沒問題的標成可付款，有問題的標出原因，留給財務人員決定。

```
瀏覽器 ──> app.py（你的電腦）──> Anthropic（LLM、harness、對話紀錄）
                                      ▲
                                      │ worker 主動向外連線領工作
                              PVE 上的 VM（sandbox）
                              ├─ /srv/ap/erp.db    模擬的 ERP（agent 唯讀）
                              ├─ /srv/ap/inbox/    供應商發票（agent 唯讀）
                              └─ /workspace/output 對帳結果
```

20 張發票裡有 10 張正常、10 張有問題（單價不符、重複請款、查無採購單、尚未驗收等），
另外埋了三張容易誤判的正常發票（分批交貨、一元的四捨五入差、兩次驗收合計）。全部是假資料。

## 檔案

| 檔案 | 用途 |
|---|---|
| `agent.md` | Agent 的設定：模型、工具、對帳規則 |
| `environment.yaml` | `self_hosted` 環境的設定 |
| `data/generate.py` | 產生假資料：ERP 資料庫與 20 張發票，以及標準答案 |
| `scripts/vm_exec.sh` | 透過 PVE 的 guest agent 在 VM 裡執行指令 |
| `scripts/deploy_data.sh` | 把假資料建到 VM 上，並清掉上一次的結果 |
| `vm/ant-worker.service` | VM 上讓 worker 常駐的 systemd 服務 |
| `vm/set-worker-key` | VM 上設定或更換環境金鑰的小工具 |
| `vm/worker-tty-log` | 把 worker 紀錄印在 VM 自己的螢幕上（給 PVE 主控台看，非必要） |
| `reconcile.py` | 命令列版：開一個 session、顯示 agent 的動作、取回結果 |
| `ask.py` | 問 agent 一個臨時問題，看它自己決定下哪些指令 |
| `verify.py` | 把 agent 的結果對照標準答案 |
| `app.py`、`web/index.html` | 網頁審核台 |

## 一步一步架起來

### 需要的東西

- Claude API 帳號（[Claude Console](https://platform.claude.com)）。Managed Agents 走 API 計費，訂閱方案不涵蓋。
- 一台 Linux 機器當 sandbox。這裡用 PVE 上的 Ubuntu VM，並啟用 QEMU guest agent。
- 自己的電腦上有 [`uv`](https://docs.astral.sh/uv/)。

### 步驟 1：在自己的電腦安裝 CLI 並登入

```bash
brew install anthropics/tap/ant
ant auth login
```

### 步驟 2：建立 agent 和 environment

```bash
ant apply --yes agent.md
ant apply --yes environment.yaml
```

執行後會產生 `claude-lock.json`，裡面記著 agent 和 environment 的 ID。後面的程式會讀它，不要刪。
這個檔案含有你帳號的組織識別碼，所以沒有放進版本庫。

### 步驟 3：產生環境金鑰

到 Console 的環境頁面，打開剛建立的 `self-hosted` 環境，產生一把環境金鑰（`sk-ant-oat01-` 開頭）。

環境金鑰和你的 API 金鑰是兩回事：

| | 放在哪 | 用途 |
|---|---|---|
| API 金鑰或 `ant auth login` 的登入 | 你的電腦 | 開 session、查詢狀態 |
| 環境金鑰 | 只放在 VM | Worker 向佇列證明身分 |

API 金鑰不要放到 VM 上，因為 agent 在 VM 裡能執行任意指令，放了它就讀得到。

### 步驟 4：準備 VM

以下在 VM 裡用 root 執行。

安裝需要的軟體：

```bash
apt-get update && apt-get install -y sqlite3 python3 curl qemu-guest-agent
```

安裝 `ant` CLI，把執行檔放到 `/usr/local/bin/ant`。下載方式見官方文件的快速入門。

建立一個沒有 sudo 權限的帳號給 worker 用，以及它的工作目錄：

```bash
useradd --create-home --shell /bin/bash worker
mkdir -p /workspace && chown worker:worker /workspace
```

建立放金鑰的檔案，只有 root 讀得到：

```bash
mkdir -p /etc/ant-worker
cat > /etc/ant-worker/env <<'EOF'
ANTHROPIC_ENVIRONMENT_ID=env_填入你的環境ID
ANTHROPIC_ENVIRONMENT_KEY=
EOF
chmod 600 /etc/ant-worker/env
```

把本專案 `vm/` 裡的兩個檔案放進 VM：

- `vm/ant-worker.service` 放到 `/etc/systemd/system/ant-worker.service`
- `vm/set-worker-key` 放到 `/usr/local/bin/set-worker-key`，並 `chmod +x`

然後設定金鑰並啟動 worker：

```bash
systemctl daemon-reload
set-worker-key
```

`set-worker-key` 會請你貼上環境金鑰（輸入時不顯示），寫入設定檔並啟動服務。之後要換金鑰也是執行它。

> Worker 本身不做隔離，agent 的 bash 工具就是一個真實的 shell。請把 worker 放在可以整台砍掉重建的
> VM 或容器裡，裡面不要放需要保護的東西。

### 步驟 5：確認 worker 在線上

回到自己的電腦：

```bash
ant beta:environments:work stats --environment-id env_填入你的環境ID
```

`workers_polling` 是 1 以上就代表 VM 上的 worker 已經在等工作。

### 步驟 6：設定連到 PVE 的方式

```bash
cp .env.example .env
```

編輯 `.env`，填入用 SSH 金鑰連到 PVE 主機的指令，以及 VM 的編號。
`scripts/vm_exec.sh` 會透過 PVE 的 `qm guest exec` 在 VM 裡執行指令，所以自己的電腦不需要能直接登入 VM。

### 步驟 7：把假資料放到 VM

```bash
uv sync
scripts/deploy_data.sh
```

這會在 VM 上建立 `/srv/ap/erp.db` 和 `/srv/ap/inbox/`，權限設成 worker 只能讀。
標準答案只存在自己電腦的 `out/expected.json`，不會放到 VM 上。

### 步驟 8：先問它一個臨時問題

```bash
uv run ask.py "這台機器的 hostname 是什麼？ERP 裡哪一家供應商的採購單總金額最高？"
```

畫面會列出 agent 自己決定執行的指令，最後回答。答案裡的 hostname 是 VM 的名字，
這就證明了指令是模型臨場決定的，而且是在你的 VM 上執行的。

同時可以在 VM 上看 worker 的紀錄，會看到領到工作和執行工具的過程：

```bash
journalctl -fu ant-worker
```

### 步驟 9：跑一次對帳並對答案

```bash
uv run reconcile.py
uv run verify.py
```

`reconcile.py` 會開一個 session、把 agent 的每個動作印出來、最後從 VM 取回 `reconciliation.json` 和 `report.md`。
`verify.py` 逐張對照標準答案，全對會顯示 `20/20 張判斷正確`。

### 步驟 10：開網頁審核台

```bash
uv run uvicorn app:app --port 8300
```

打開 <http://localhost:8300>，按「重新對帳」。Agent 執行期間頁面會即時顯示進度，
完成後左邊列出有疑問的發票，右邊顯示三方比對的數字，可以逐張核准付款或退回供應商。

## 一次執行的實際流程

以「這台機器的 hostname 是什麼」為例：

1. 【Anthropic】Harness 把 system prompt 和問題送給 LLM。
2. 【Anthropic】LLM 輸出：我要呼叫 bash，指令是 `hostname`。這時什麼都還沒執行。
3. 【Anthropic】Harness 把這個工具呼叫放進佇列。
4. 【你的 VM】Worker 領走它，執行 `hostname`。
5. 【你的 VM → Anthropic】Worker 把結果送回去。
6. 【Anthropic】Harness 把結果接進對話，再送給 LLM。
7. 【Anthropic】LLM 輸出最後的回答。

只有第 4 步發生在你的機器上。

## 注意

- 每跑一次都會消耗 API 額度。同樣的對帳工作，執行時間從不到 30 秒到兩分多鐘都出現過，
  因為 agent 每次自己決定的步驟不同。
- 審核台只監聽 localhost，沒有登入機制，不要對外開放。
- 自行託管的沙箱目前是 Beta，不能在建立 session 時掛載檔案或 GitHub repo。
- VM 用 DHCP 取得 IP 的話，從範本複製出來後記得重新產生 `/etc/machine-id`，否則可能和原本的機器搶同一個 IP。
