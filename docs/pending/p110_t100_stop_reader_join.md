---
pid: "p110"
slug: "t100_stop_reader_join"
status: "todo"
---
# p110 t100 minor：stop() 对仅 reader 残留的关闭资源补 abort+join

- 来源：t100 Round 1 代码复审 minor finding `t100_code_f001`（review_code.md，overall PASS）。
- 内容：`IdleWatcherManager.stop()` 的关闭中资源循环只 join 执行线程；当某关闭资源的执行线程已退出、仅 provider reader 线程残留时，旧实现（t100 之前）会对其 abort 并 join 至停机 deadline，新实现整项跳过，`stop()` 可在 reader 仍存活时返回。席位登记仍保留、配额核算不受影响，仅停止等待语义弱一档。修法：关闭循环中对每个资源先 abort provider，再依次以剩余 deadline join 执行线程与 reader 线程，并补一条真实线程用例（执行线程已退出、reader 挂起时 stop() 等待 reader 退出或 deadline 到期）。
- 处理：未开
