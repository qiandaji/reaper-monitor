-- reaper-monitor: 在 REAPER 标题栏显示本机局域网 IP
-- 依赖：JS_ReaScriptAPI（本机已装 reaper_js_ReaScriptAPI64ARM.dylib）
-- 用法：Actions → Show action list → 搜索 reaper-monitor_ip_title 运行一次；
--       控制台会打印 IP（兜底），标题栏会追加「｜ 本机IP: x.x.x.x」。
-- 自动常驻：SWS → Set global startup action 设为全局启动动作。

local function get_lan_ips()
  local ret, out = reaper.ExecProcess(
    "ifconfig | grep 'inet ' | grep -v '127.0.0.1' | awk '{print $2}'", 3)
  if out and out ~= "" then
    out = out:gsub("%s+$", "")
    out = out:gsub("%s*\n%s*", " / ")
    if out ~= "" then return out end
  end
  local f = io.popen and io.popen("ipconfig getifaddr en0 2>/dev/null")
  if f then
    local s = f:read("*a")
    f:close()
    if s then
      s = s:gsub("%s+$", "")
      if s ~= "" then return s end
    end
  end
  return "未获取到局域网 IP"
end

local function run()
  local hwnd = reaper.GetMainHwnd()
  reaper.ShowConsoleMsg("reaper-monitor 本机IP: " .. get_lan_ips() .. "\n")
  local next_t = 0
  local function tick()
    local now = reaper.time_precise()
    if now >= next_t then
      next_t = now + 2
      local ok_title, title = pcall(reaper.JS_Window_GetTitle, hwnd)
      local clean = ok_title and (title or "") or ""
      clean = clean:gsub("%s*｜ 本机IP:.*$", "")
      clean = clean:gsub("%s*| 本机IP:.*$", "")
      local ok_set = pcall(reaper.JS_Window_SetTitle, hwnd,
        clean .. " ｜ 本机IP: " .. get_lan_ips())
      if not ok_set then
        reaper.ShowConsoleMsg("reaper-monitor: 设置标题栏失败，请确认 JS_ReaScriptAPI 已加载\n")
        return
      end
    end
    reaper.defer(tick)
  end
  tick()
end

run()
