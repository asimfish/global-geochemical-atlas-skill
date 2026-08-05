# Q14 稳健异常

严格按 `inputs/anomaly_policy.json` 处理 `inputs/values.csv`：正值取 `log10`，中心为 median，尺度为 `1.4826 × MAD`，`|robust_z| >= 3.5` 标异常。若 MAD=0，使用 policy 指定的严格经验分位数回退，不除零、不加任意 epsilon。

输出 `group_statistics.csv` 和 `anomalies.csv`。中心、尺度和 z 至少保留 8 位小数。
