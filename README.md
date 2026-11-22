# reaper-monitor — 乐队排练 Web 低延迟监听

乐队排练时，乐手在同一局域网内用**手机浏览器**监听自己的混音，并独立控制
指定源轨道的响度与静音。音频从 REAPER 监听母线经 **ReaStream（UDP）** 转发到本服务，
再经 **WebSocket** 送到手机；控制命令经 **OSC** 写回 REAPER。

**监听轨道是动态发现的**：REAPER 工程里实际建立了几条监听母线，网页就自动出现几个
入口，不需要在配置文件里登记乐手。

## 工作原理

```
REAPER 工程
  ├─ 源轨（鼓/贝斯/吉他/人声…）
  │    └─ send → 各监听母线（send 名称 = 目标母线轨道名）
  ├─ MON 鼓手（监听母线）←────────────────────┘
  │    └─ FX: ReaStream（identifier = 轨道名）──UDP 58710──┐
  ├─ MON 贝斯  ── ReaStream ──────────────────────────────┤
  └─ …                                                     ▼
                                             reaper-monitor 服务（本机）
                                             ├─ ReaStream 接收（按 identifier 分路）
                                             ├─ WS 音频 → 手机 AudioWorklet 播放
                                             └─ WS 控制 ↔ OSC ↔ REAPER
```

- 每位乐手一条**监听母线**。母线音量/静音 = 他的"总音量/总静音"。
- 网页上"分轨响度/静音"控制的是**源轨 → 该母线**的 send 音量；
  REAPER 官方 OSC 没有 send 静音，静音用 send 音量 = 0 实现，恢复时回到静音前的值。
- 默认立体声。ReaStream 每个数据报样本块有限，立体声时要求
  **REAPER 音频设备块大小 ≤128 采样**（见"延迟调优"）。

## 端口总览

| 用途 | 端口 | 说明 |
|---|---|---|
| 手机访问（HTTP/WS） | 61390 | 页面、音频与控制 WebSocket |
| OSC → REAPER | 9212 | REAPER 控制面"接收端口" |
| OSC 反馈监听 | 9213 | REAPER 控制面"发送端口" |
| ReaStream UDP | 58710 | ReaStream 默认端口 |

可用 `.env`（复制 `.env.example`）覆盖，变量前缀 `RMP_`。

---

# 部署

## 方式 A：下载 Release（推荐）

1. 在 GitHub 仓库右侧 **Releases** 下载最新的 `reaper-monitor-v*.zip` 并解压。
2. 按下面「详细使用指南」从第一步开始即可（REAPER 配置 + 双击启动脚本）。

## 方式 B：源码运行

```bash
git clone https://github.com/qiandaji/reaper-monitor.git
cd reaper-monitor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 61390   # 或直接双击启动脚本
```

> 启动脚本（`start_macos.command` / `start_windows.bat`）会自动创建虚拟环境并安装依赖，
> 日常使用推荐直接双击脚本，无需手动执行上面的命令。

---

# 详细使用指南

## 第一步：启动服务（在运行 REAPER 的这台电脑上）

- **macOS**：双击 `start_macos.command`（首次运行自动创建 .venv 并安装依赖）。
- **Windows**：双击 `start_windows.bat`。

窗口保持打开。启动成功后可访问 `http://127.0.0.1:61390/api/health` 看到
`"ok": true`。

## 第二步：REAPER 配置 OSC 控制面（一次性）

REAPER 菜单 **Preferences → Control/OSC/web → Add → OSC (Open Sound Control)**：

- **Mode** 选 `Configure device IP + local port`
- **Listen port**（REAPER 自己监听的端口，服务把命令发到这里）：`9212`
- **Device IP**：本机填 `127.0.0.1`（服务与 REAPER 在同一台电脑）
- **Device port**（REAPER 把轨道名等反馈发到设备的这个端口）：`9213`
- **Pattern config** 下拉选择 `reaper-monitor.ReaperOSC`
  （已复制到 REAPER 资源目录，下拉直接可选；项目目录里保留原件）

> 端口必须与服务的 `.env` 一致。控制面选好后建议重启一次 REAPER 让它加载
> 新的 pattern 文件。

## 可选：在 REAPER 标题栏显示本机 IP

外出排练想快速知道本机 IP 时，可以让 REAPER 标题栏一直显示局域网 IP：

1. 确认已安装 **JS_ReaScriptAPI** 扩展（ReaPack 里搜 `js_ReaScriptAPI`）与 **SWS**。
2. 把仓库 `scripts/reaper-monitor_ip_title.lua` 复制到 REAPER 资源目录的 `Scripts/`
   文件夹（macOS：`~/Library/Application Support/REAPER/Scripts/`）。
3. REAPER 里 Actions → **Show action list** → 搜 `reaper-monitor_ip_title` 运行一次：
   ReaScript 控制台会打印 IP，主窗口标题栏会追加 `｜ 本机IP: x.x.x.x`。
4. 想开机自动常驻：搜 **SWS: Set global startup action**，把它设为全局启动动作。
   不想常驻时再执行一次 **SWS: Clear global startup action** 即可。

> 标题栏每 2 秒刷新一次；切换 WiFi 后 IP 会自动跟着变。

## 第三步：在 REAPER 里建立监听母线

每位乐手一条轨道（示例：鼓手监听）：

1. **新建轨道**，命名为 `MON 鼓手`（默认前缀 `MON `，可在 `data/config.json`
   里改 `monitor_prefix`；注意前缀含一个空格）。
2. 在这条轨道上插入 FX：**VST: ReaStream**，设置：
   - **identifier**：`MON 鼓手`（**必须与轨道名完全一致**，这是分路的依据）
   - **destination**：`<这台电脑IP>:58710`，勾选 **Send audio/MIDI**
3. 重复以上步骤，为每位乐手建一条（如 `MON 贝斯`、`MON 主唱`…）。
4. 监听母线本身记得把 Master Send 关掉或调小，避免重复出声（可选）。

## 第四步：源轨发送（send）到各监听母线

这是"每人独立混音"的关键：**每个源轨都要向每位乐手的监听母线发一个 send**。

1. 打开源轨（如 `鼓`）的 **Routing/I-O 面板**，在 Sends 区 Add new send，
   目标选 `MON 鼓手`。
2. **send 的名称必须等于目标监听母线轨道名**（`MON 鼓手`）。REAPER 新建
   send 时默认就用目标轨道名，一般不需要改；如果改过名，请改回与监听母线
   轨道名一致。
3. 按同样方式给 `MON 贝斯` 等其它母线也建 send。
4. 对每条源轨重复。

> 与旧版不同：**send 顺序不再重要**，服务会按 send 名称自动匹配到对应母线。
> 没建 send 的源轨，乐手页面会提示并拒绝操作。

## 第五步：乐手用手机监听

1. 手机连**同一 WiFi**。
2. 浏览器打开 `http://<这台电脑IP>:61390`（电脑 IP 见启动脚本提示、REAPER 标题栏，或
   macOS 用 `ipconfig getifaddr en0` 查看）。
3. 页面自动列出 REAPER 里实际建立的监听母线（每 3 秒刷新，工程打开后自动出现）。
4. 乐手点自己的母线进入混音页，调节：
   - **总音量 / 总静音** → 控制他的监听母线；
   - **每个源轨的响度 / 静音** → 控制源轨到他母线的 send 音量。
5. 所有操作实时写回 REAPER。

## 安卓手机：独立 App（推荐，延迟更低）

安卓系统的浏览器音频输出缓冲天生比 iOS 大（约 40–100ms），网页无法调小；推荐安卓乐手用配套原生 App，走系统低延迟音频通道（AudioTrack `PERFORMANCE_MODE_LOW_LATENCY`），和 iPhone 网页版一样跟手。**测试请用有线耳机**（蓝牙耳机延迟 100–300ms，任何软件都救不了）。

- 工程目录：`../reaper-monitor-android/`（与本项目同级），Android Studio 直接打开即可。
- 现成 APK：`reaper-monitor-android/app/build/outputs/apk/debug/app-debug.apk`，传到手机侧载安装。
- 构建与侧载步骤、使用说明见 `reaper-monitor-android/README.md`。
- App 与网页连的是**同一个服务**（`http://<电脑IP>:61390`），REAPER 配置完全不变，只换手机端。
- iOS 乐手继续用浏览器即可，无需 App。

## 动态发现规则（重要约定）

| 项目 | 约定 |
|---|---|
| 监听母线识别 | 轨道名以 `monitor_prefix`（默认 `MON `）开头 |
| 源轨 | 其余所有轨道（按轨道号升序显示） |
| 乐手 id | 监听母线的轨道号（网页 URL 里的 `?id=3`） |
| ReaStream identifier | 与监听母线轨道名**完全一致** |
| 源轨 send 名称 | 与目标监听母线轨道名**完全一致** |

## 延迟调优

- REAPER 音频设备块大小设 **128 采样**（立体声上限；64 更小但很多设备/驱动会爆音失真，实测 128 最稳）。
- 手机与电脑走 **5GHz WiFi**，路由器离排练位近；**避免蓝牙耳机**（A2DP 延迟大）。
- ReaStream 是"发多少收多少"，不重传；WiFi 信号差会表现为爆音/断续。
- **安卓设备延迟比 iPhone 大**：这是安卓浏览器的输出缓冲上限，网页无法调小；
  安卓乐手请用**独立安卓 App**（见"安卓 App"章节）达到接近 iPhone 的延迟。
- 安卓务必用**有线耳机或外放**测：蓝牙耳机（A2DP）额外加 100–300ms，是最常见的"明显延迟"来源。
- 部分安卓手机默认开音效增强（杜比/均衡器/环绕），系统设置里关掉再测，通常能再省一些。
- 若手机浏览器无声音：点一下页面任意位置（移动端音频需用户手势解锁）。
- 老 iOS Safari 无 AudioWorklet，页面会自动回退 ScriptProcessor，延迟会再高约 20ms，属设备能力上限。

## 故障排查

| 现象 | 检查 |
|---|---|
| 网页提示"未发现监听轨道" | REAPER 是否打开工程？OSC 控制面是否加载 `reaper-monitor.ReaperOSC`？监听母线名是否以 `MON ` 开头？页面每 3 秒自动刷新，无需手动刷新 |
| 选人页能进、混音页没声音 | 监听母线上的 ReaStream identifier 是否等于轨道名？destination 是否为 `电脑IP:58710`？电脑防火墙是否放行 UDP 58710？ |
| 分轨推子报"没有到…的 send" | 该源轨上没有到这条监听母线的 send，或 send 名称与母线轨道名不一致 |
| 推子动、REAPER 没反应 | OSC 端口：REAPER Listen port 是否 = 9212、Device IP/port 是否 = 127.0.0.1:9213（与 .env 一致）？ |
| `/api/health` 的 `gateway.listening` 为 false | 9213 被占用，或 REAPER 未启动（反馈未建立不影响 listening，true 才正常） |
| 音频断续/爆音 | 块大小 ≤128？改用 5GHz WiFi？手机离路由器近一点？ |
| 安卓明显比 iPhone 延迟大 | 换有线耳机；关系统音效增强；使用独立安卓 App（网页方案受浏览器输出缓冲上限限制） |

## 配置（data/config.json）

```json
{
  "monitor_prefix": "MON "
}
```

- `monitor_prefix`：监听母线轨道名前缀（改后重启服务）。
- 不需要登记乐手、源轨或 stream_id——全部由 REAPER 工程动态决定。

## 限制与后续

- 不含电平表、声像、快照；核心功能为分轨响度/静音 + 总音量/静音。
- 假设立体声、恒定块大小；服务端已按完整块重组，兼容偶发多包拆分，
  但**首包前无法得知块大小**，请遵守块大小建议。
- 每个 ReaStream 流只支持一位乐手；多乐手需要多条监听母线。

## 目录结构

```
reaper-monitor/
├─ app/                    # FastAPI 服务
│  ├─ main.py              # HTTP/WS 路由与生命周期
│  ├─ reastream.py         # ReaStream UDP 解析
│  ├─ streams.py           # 音频按 identifier 扇出到各 WebSocket
│  ├─ osc_gateway.py       # OSC ↔ REAPER 控制
│  ├─ discovery.py         # 监听母线 / 源轨动态发现
│  ├─ config.py / state.py
│  └─ static/              # 手机网页（原生 JS，无构建）
├─ data/config.json        # monitor_prefix 配置
├─ reaper-monitor.ReaperOSC  # REAPER OSC pattern（需复制到 REAPER 资源目录）
├─ tests/                  # pytest（24 个用例）
└─ start_macos.command / start_windows.bat
```

## 测试

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests -q
```
