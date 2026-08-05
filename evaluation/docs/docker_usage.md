# Docker 使用与测试指南

> 更新时间：2026-08-05（HKT）
> 适用主机：`bjzgcUbuntu`（2 × NVIDIA GeForce RTX 5090）
> 适用项目目录：`/home/ubuntu/Hackathon`

本文说明如何使用已配置的 Docker 环境、构建 E1 合同镜像并验证隔离能力。验收时必须区分 Docker CLI、daemon、普通容器运行时和正式 E1 smoke；仅有 `docker --version` 输出不能证明 Docker 全链路可用。

当前普通 Docker 使用、镜像构建、内存/PID/只读根文件系统/网络/GPU 隔离均已验证通过。rootless user slice 尚未委派 CPU controller，因此正式 E1 smoke 会按设计失败关闭；在管理员完成解锁并重新测试前，不得标记为正式验收通过。

## 1. 快速开始

```bash
ssh bjzgcUbuntu
docker context use rootless
systemctl --user status docker.service --no-pager
docker version
docker info
docker run --rm hello-world
```

`docker version` 应同时显示 Client 和 Server，`hello-world` 应正常退出。若只显示 Client，说明 CLI 已安装，但 daemon 或 socket 仍不可用。

## 2. 当前配置

| 项目 | 当前值 | 说明 |
|---|---|---|
| 操作系统 | Ubuntu 22.04.5 LTS | 内核 `6.8.0-124-generic` |
| Docker | 28.4.0 | rootless daemon |
| Buildx | 0.27.0 | Docker 构建插件 |
| Compose | 2.39.2 | 使用 `docker compose` |
| Docker context | `rootless` | socket：`/run/user/1000/docker.sock` |
| 存储与 cgroup | overlay2；cgroup v2 | 已委派 memory、pids，未委派 cpu/cpuset |
| 合同镜像 | `localhost/e1-contract-runner:bjzgc-rootless` | 构建和 smoke 使用此引用 |

## 3. 日常操作

查看 context、镜像、容器和资源占用：

```bash
docker context ls
docker images
docker ps
docker ps -a
docker stats
```

运行容器、查看日志并进入容器：

```bash
docker run --rm hello-world
docker run -d --name docker-cli-test --network none alpine:3.20 sleep 300
docker logs -f docker-cli-test
docker exec -it docker-cli-test sh
docker stop docker-cli-test
docker rm docker-cli-test
```

构建镜像和使用 Compose：

```bash
docker build -t my-image:dev .
docker build --no-cache -t my-image:dev .
docker compose config
docker compose up -d
docker compose logs -f
docker compose down
```

临时容器优先使用 `--rm`。清理镜像、容器或构建缓存属于破坏性操作，只删除已确认不再使用的对象。

## 4. E1 项目工作流

先运行一键自检：

```bash
cd /home/ubuntu/Hackathon
bash eval/environment/docker/scripts/check-docker-cli.sh
```

返回码含义：

| 返回码 | 含义 |
|---|---|
| `0` | CLI、Buildx、Compose 和 daemon 均可用 |
| `2` | CLI 完整，但 daemon/socket 不可用 |
| `127` | Docker CLI 未安装或不在 `PATH` |

运行专项测试和正式 smoke：

```bash
cd /home/ubuntu/Hackathon
python3 -m pytest -q eval/environment/docker

IMAGE_REF=localhost/e1-contract-runner:bjzgc-rootless \
  eval/environment/docker/scripts/run-contract-smoke.sh
```

当前宿主系统的 `jsonschema` 版本较旧，宿主 pytest 中对应 6 项会失败；相同 6 项已在锁定 Python 3.12 依赖的合同工具容器内通过。正式验收仍以完整证据和完成标记为准。

## 5. 重建合同镜像

```bash
cd /home/ubuntu/Hackathon
CONTAINER_ENGINE=docker \
IMAGE_REF=localhost/e1-contract-runner:bjzgc-rootless \
  eval/environment/docker/scripts/build-contract.sh
```

当前已验证的构建信息：

```text
image_ref:  localhost/e1-contract-runner:bjzgc-rootless
image_id:   sha256:7d7dfd081eba34dbaffe0cb6dc3e3427abc821c0085e27a19f6e1685690a1d33
evidence:   /home/ubuntu/Hackathon/eval/environment/docker/evidence/contract-build-20260805T150840Z
profile:    e1-default-v1
```

构建完成后校验证据清单：

```bash
cd /home/ubuntu/Hackathon/eval/environment/docker/evidence/contract-build-20260805T150840Z
sha256sum -c SHA256SUMS
```

## 6. 验收分层

| 层级 | 通过条件 | 当前结果 |
|---|---|---|
| CLI | Docker、Buildx、Compose 均能输出版本 | PASS |
| daemon | `docker version` 同时显示 Client/Server，`docker info` 成功 | PASS（rootless） |
| runtime | `docker run --rm hello-world` 成功 | PASS |
| 镜像构建 | 合同镜像构建完成且 `SHA256SUMS` 全绿 | PASS |
| 非 CPU 隔离 | 内存、swap、PID、只读根、tmpfs、cap-drop、无网络、GPU=0 | PASS |
| CPU 隔离 | `--cpus 2` 能写入并生效 | FAIL_CLOSED |
| 正式 E1 smoke | 生成 `DOCKER_SMOKE_COMPLETE` 且所有证据校验通过 | 未完成，等待 CPU controller 解锁 |

## 7. 故障排查

### daemon 无法连接

```bash
docker context use rootless
systemctl --user restart docker.service
systemctl --user status docker.service --no-pager
docker version
```

### 镜像拉取超时

确认 `~/.config/docker/daemon.json` 中 registry mirror 配置仍在，再重启用户级 Docker。正式 E1 镜像仍应使用 digest 固定版本，不能把镜像源变化当成可接受漂移。

### 磁盘空间不足

```bash
df -h
docker system df
docker images
docker ps -a
```

当前主机磁盘使用率较高，构建前应确认有足够空间。不要未经确认直接运行批量清理命令。

### CPU 配额报错

若出现 `NanoCPUs can not be set`，表示当前 rootless 用户 slice 没有 CPU controller。这不是镜像或脚本错误，不应绕过 CPU probe 或伪造完成标记。

## 8. 管理员解锁正式验收

管理员可选择以下一种方式：

1. 将 `ubuntu` 加入系统 daemon 的 `docker` 组，重新登录后切换到 `default` context。Docker 组属于高权限边界，只能授予受信账号。
2. 为 `user@1000.service` 或对应 user slice 显式委派 `cpu cpuset io memory pids`，然后重启用户 manager 和 rootless Docker。

解锁后重新执行：

```bash
docker run --rm --cpus 2 --memory 4g --pids-limit 256 hello-world

cd /home/ubuntu/Hackathon
IMAGE_REF=localhost/e1-contract-runner:bjzgc-rootless \
  eval/environment/docker/scripts/run-contract-smoke.sh
```

只有 CPU probe 通过、正式 smoke 生成 `DOCKER_SMOKE_COMPLETE`，且相关 `SHA256SUMS` 全部校验通过，才能把正式 E1 Docker 验收标记为 PASS。
