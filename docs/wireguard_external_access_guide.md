# WireGuard 外部访问操作指南

本文用于让外部人员通过 WireGuard 访问规划网站，而不是把网站端口直接暴露到公网。

## 当前本机配置

本机已存在 WireGuard 接口，当前可用于网站绑定的地址如下：

| 接口 | 本机地址 | 说明 |
| --- | --- | --- |
| `wg0` | `10.88.0.3` | 推荐优先使用 |
| `wg0-ws` | `10.7.0.3` | 通过 wstunnel 转发的 WireGuard |
| `wg15-ws` | `10.15.0.3` | 通过 wstunnel 转发的 WireGuard |

网站访问端口默认使用 `8866`。

推荐启动方式：

```bash
cd /home/yzk/cap_plan/power_plan_web
POWER_PLAN_WG_HOST=10.88.0.3 scripts/start_wireguard_web.sh
```

启动后，已加入同一个 WireGuard 网络的访问者打开：

```text
http://10.88.0.3:8866/
```

如果实际使用 `wg0-ws` 或 `wg15-ws`，将启动命令和访问地址改为对应地址：

```bash
POWER_PLAN_WG_HOST=10.7.0.3 scripts/start_wireguard_web.sh
POWER_PLAN_WG_HOST=10.15.0.3 scripts/start_wireguard_web.sh
```

对应访问地址：

```text
http://10.7.0.3:8866/
http://10.15.0.3:8866/
```

## 本机管理员操作

1. 停掉原来只监听本机的服务。

```bash
ss -ltnp | grep ':8866'
kill <上面看到的 python 进程号>
```

2. 用 WireGuard 地址启动网站。

```bash
cd /home/yzk/cap_plan/power_plan_web
POWER_PLAN_WG_HOST=10.88.0.3 scripts/start_wireguard_web.sh
```

3. 确认监听地址正确。

```bash
ss -ltnp | grep ':8866'
```

正确结果应包含：

```text
10.88.0.3:8866
```

如果仍显示 `127.0.0.1:8866`，说明网站还只允许本机访问。

4. 确认不要开启本地免登录。

启动脚本默认设置：

```text
POWER_PLAN_LOCAL_AUTH_BYPASS=0
```

不要在给外部人员访问时使用 `POWER_PLAN_LOCAL_AUTH_BYPASS=1`。

## WireGuard 服务端管理员操作

外部人员能否访问，取决于他们是否被加入同一个 WireGuard 网络。仅在本机启动网站还不够，WireGuard 服务端还需要添加访问者 peer。

以 `10.88.0.0/24` 网络为例，给访问者分配一个未占用地址，例如：

```text
10.88.0.21
```

服务端配置中新增访问者 peer：

```ini
[Peer]
PublicKey = <访问者的 PublicKey>
AllowedIPs = 10.88.0.21/32
```

如果 WireGuard 服务端默认不允许 peer 之间互访，需要在服务端开启转发并放行 `10.88.0.21 -> 10.88.0.3:8866` 的 TCP 流量。

访问者只需要访问本机 WireGuard 地址，不需要访问公网 IP：

```text
http://10.88.0.3:8866/
```

## 访问者 Windows 操作

1. 安装 WireGuard 客户端。

下载地址：

```text
https://www.wireguard.com/install/
```

2. 从 WireGuard 管理员处获取配置文件，例如：

```text
power-plan-wg.conf
```

3. 打开 WireGuard，点击“从文件导入隧道”，选择该配置文件。

4. 点击“激活”。

5. 打开命令提示符，测试连通性。

```bat
ping 10.88.0.3
```

6. 如果电脑或浏览器设置了代理，把 `10.88.0.0/24` 或至少 `10.88.0.3` 加入“不使用代理/绕过代理”的地址列表。

7. 浏览器打开网站。

```text
http://10.88.0.3:8866/
```

8. 使用分配的账号登录。没有账号时联系管理员创建账号或确认是否允许注册。

## 访问者 macOS 操作

1. 安装 WireGuard。

可以从 App Store 安装 WireGuard。

2. 导入管理员提供的 `power-plan-wg.conf`。

3. 启用隧道。

4. 在终端测试：

```bash
ping 10.88.0.3
```

5. 浏览器打开：

```text
http://10.88.0.3:8866/
```

如果浏览器启用了代理，请把 `10.88.0.0/24` 或 `10.88.0.3` 加入代理绕过列表。

## 访问者 Linux 操作

1. 安装 WireGuard。

Ubuntu / Debian：

```bash
sudo apt update
sudo apt install wireguard
```

2. 保存管理员提供的配置文件：

```bash
sudo cp power-plan-wg.conf /etc/wireguard/power-plan-wg.conf
sudo chmod 600 /etc/wireguard/power-plan-wg.conf
```

3. 启动隧道。

```bash
sudo wg-quick up power-plan-wg
```

4. 测试连通性。

```bash
ping 10.88.0.3
curl --noproxy '*' -i http://10.88.0.3:8866/
```

5. 浏览器打开：

```text
http://10.88.0.3:8866/
```

停止隧道：

```bash
sudo wg-quick down power-plan-wg
```

## 访问者配置文件模板

下面是访问者侧配置模板。真实配置必须由 WireGuard 管理员填入密钥、服务端地址和分配的 IP。

```ini
[Interface]
PrivateKey = <访问者自己的 PrivateKey>
Address = 10.88.0.21/32
DNS = 1.1.1.1

[Peer]
PublicKey = <WireGuard 服务端 PublicKey>
Endpoint = <WireGuard 服务端公网地址或隧道入口>:<端口>
AllowedIPs = 10.88.0.0/24
PersistentKeepalive = 25
```

说明：

- `Address` 每个访问者必须唯一。
- `AllowedIPs = 10.88.0.0/24` 表示只把 WireGuard 内网流量走隧道，不影响访问者普通上网。
- 如果服务端使用 wstunnel 或其他封装，访问者应使用管理员提供的完整配置，不要自行改 endpoint。

## 常见问题

1. `ping 10.88.0.3` 不通。

说明 WireGuard 网络还没通。检查访问者配置是否启用、服务端是否添加 peer、服务端是否允许 peer 之间转发。

2. `ping 10.88.0.3` 通，但网页打不开。

检查本机网站是否绑定到 `10.88.0.3:8866`：

```bash
ss -ltnp | grep ':8866'
```

再检查防火墙是否放行 WireGuard 网络访问 `8866/tcp`。

如果返回代理错误或 502，检查访问者电脑、浏览器或命令行是否配置了 HTTP 代理。WireGuard 内网地址应绕过代理，至少把 `10.88.0.3` 加入不代理列表。

3. 页面提示需要登录。

这是正常情况。外部访问不应使用本地免登录。请使用管理员分配的账号登录。

4. 想换成 `10.7.0.3` 或 `10.15.0.3`。

本机启动命令和访问者配置中的目标地址要一起修改。访问者必须加入对应的 WireGuard 网络，否则无法访问。
