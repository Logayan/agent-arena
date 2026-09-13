# Runtime 取证与故障注入执行环境

本项目根目录就是正式 `delivery/`。它只使用 Python 标准库，不读取环境变量或 Provider 凭据。

## 命令

```bash
python run_runtime_probe.py build
python -m unittest discover -s tests -v
python run_runtime_probe.py write-manifest
python run_runtime_probe.py verify
python run_runtime_probe.py gate config/candidate-v1.json  # 预期退出 42
```

`build` 会冻结 `.jianghu-platform-evidence`、按 registry 复算正式 Artifact 原始字节、生成证据索引、执行两个真实本地子进程故障场景，并运行预声明失败关闭门禁。冻结投影：6003 events / sequence 1..6015 / SHA-256 `41171e25f262f44f71aad2273dbac20c556bd807ca95c8ac1ff036aef38ebc40`。

正式结论：本地工程 `PASS`；全 Runtime 迁移 `NO_GO`；OpenClaw 退役 `REJECTED`。
