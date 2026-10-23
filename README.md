# uefi-clover

面向 **小米平板 4 8 英寸 LTE 版**（`clover`，`xiaomi,clover-lte`，高通 **SDM660**）的
Mu-Silicium 设备包。它与同级仓库 `UniXNU-clover`（负责 XNU 和 boot 镜像）一起，
组成一次 UniXNU 移植的 UEFI 那一半。

它是**叠加层，不是 fork**：这里的文件会被放进一个普通的
`Project-Silicium/Mu-Silicium` 检出中使用。

```
Platforms/Xiaomi/cloverPkg/clover.dsc            平台描述
Platforms/Xiaomi/cloverPkg/clover.fdf            固件卷布局
Platforms/Xiaomi/cloverPkg/clover.dec            占位文件，上游这些包也留空
Platforms/Xiaomi/cloverPkg/DeviceBuild.py        stuart 构建器 build_uefi.py 要求的入口
Platforms/Xiaomi/cloverPkg/Include/APRIORI.inc   clover 的 DXE apriori 顺序
Platforms/Xiaomi/cloverPkg/Include/DXE.inc       模块列表
Platforms/Xiaomi/cloverPkg/Include/RAW.inc       SecParti.cfg 等原始数据
Platforms/Xiaomi/cloverPkg/Drivers/CloverGopDxe  在 splash 窗口上发布 GraphicsOutput
Platforms/Xiaomi/cloverPkg/Library/MemoryMapLib          clover 自己的 DDR 内存图
Platforms/Xiaomi/cloverPkg/Library/ConfigurationMapLib   SDM660 寄存器表
Resources/Configs/clover.toml                    固件卷几何、boot 镜像打包
Resources/DTBs/clover.{dtb,dts}                  本机自己的板级设备树，从它的 boot 镜像里切出
BootShim/BootShim.S                              上游 shim，外加一处 Image Size 修正
proprietary-files.txt                            必须从平板里提取的东西
scripts/apply-clover-overlay.py                  把叠加层复制进检出
scripts/check-clover-uefi.py                     校验结果，并核对两个仓库是否一致
scripts/extract-clover-blobs.py                  用本机自己的 xbl 生成 Binaries/clover
scripts/clockdxe_patch.py                        对 ClockDxe 做上游那六处改动
scripts/fetch-mu-silicium.sh                     按固定 SHA 拉取检出，走镜像
scripts/build-clover-uefi.sh                     colima 客户机，然后跑 EDK II 构建
scripts/seed-clover-extdeps.py                   填充 stuart extdep 缓存
scripts/fv-order.py                              FVMAIN 文件序号，独立构建路径用
scripts/decode-boot-header.py                    打印 boot 镜像头，兼容两种几何
scripts/split-clover-dtbs.py                     从 stock boot 镜像里切出 DTB 表
scripts/scan-clover-dtbs.sh                      给每条 DTB 记录命名
```

厂商 blob 放在 `Binaries/clover` 下，已加入 gitignore，来源是本机自己的固件，
而不是 Device-Binaries（后者没有 clover 目录）。`proprietary-files.txt` 是它可审查的清单。

## 固件眼中的这台平板

| 项目 | 值 |
| --- | --- |
| SoC | Qualcomm SDM660 |
| 芯片包 | `Silicon/Qualcomm/StarlordPkg` |
| 板 id | `qcom,msm-id = <317 0>`、`qcom,board-id = <0x0001000b 0>` —— 平台 11（MTP）+ 子类型 1，读自真机 merged dtb |
| 核心 | 8 个 CPU，`reg` 0x0-0x3（part `0x801`）和 0x100-0x103（part `0x800`），`enable-method = "psci"` |
| GIC | distributor `0x17A00000` + `0x10000`，redistributor `0x17B00000` + `0x100000`，stride `0x20000` |
| 时基 | 19.2 MHz |
| DRAM | `0x80000000` + `0x80000000`；第二个 bank `0x100000000` + `0x7E4C0000` 尚未描述 |
| 屏幕 | 1200×1920，32 bpp，splash 移交地址 `0x9D400000` + `0x2400000` |
| 存储 | eMMC（`sdhc_1` @ `0x0c0c4000`），没有 UFS |
| 控制台 | `blsp1_uart2` @ `0x0C170000`，115200 |
| 固件卷 | `0x9FC00000` + `0x300000` |
| boot 镜像 | header v0，页 4096，base 0，kernel `0x8000`，ramdisk `0x1000000`，tags `0x100` |

splash 窗口的地址来自实机测量，不是设备树读数：`sdm660-common.dtsi` 与
`clover-overlay.dtsi` 说法不一致，而**本机** xbl 里的 `uefiplat.cfg` 把
`0x9D400000` + `0x2400000` 保留为 "Display Reserved"，且在 UEFI 运行之前
stock xbl 已经往这段里画过东西。`MemoryMapLib.c`、`clover.toml` 和 ADT 用的都是这个地址。

这个固件卷里没有 ramdisk 文件系统驱动。`Fat` 和 `PartitionDxe` 会被调度，
但它们能看到的唯一 `BlockIo` 来自 `SdccDxe`，所以 UniXNU payload 不可能搭
boot 镜像的 ramdisk 进来：它必须是 eMMC 分区上的一个 FAT 卷
（`cache`，`mmcblk0p49`），boot 镜像则完全不带 ramdisk。
`ramoops`/pstore 想要 `0x9FE00000`，那在固件卷范围内，所以 panic 只能走 UART。

`uefiplat.cfg` 的 `[MemoryMap]` 和 `[RegisterMap]` 已逐行抄进 `MemoryMapLib`，
27 个 `[ConfigParameters]` 键抄进 `ConfigurationMapLib`。内存图止于 `0xA0000000`。

boot 镜像是 v0：本机的 `boot` 和 `recovery` 两个分区 header version 都是 0，
`page_size` 0x1000，加载偏移是相对 base 的，`0x80000000` 留给 ABL 自己加。
它们的 kernel 段是 `Image.gz`，gzip 流后面串着设备树，由 `qcom,msm-id` /
`qcom,board-id` 挑选。这个叠加层带的 DTB 是那张 111 条记录的表里的第 `037` 条
—— 唯一带 `qcom,mdss_dsi_nt51021_boe_wuxga_video` 的 sdm660 blob。

## 显示

这个固件卷不初始化显示，只接管 ABL 留下的那一套。ABL 启动时已经把 MDSS、
nt51021 面板和 pm660l 背光点亮，并且正在扫描 "Display Reserved" 窗口
（`0x9D400000`，1200×1920，32 bpp）；固件卷里没有任何模块去改这些硬件。

`Drivers/CloverGopDxe` 是卷里唯一的 GOP 生产者：在这段窗口上发布单模式
`GraphicsOutput`（`PixelBlueGreenRedReserved8BitPerColor`），`Blt` 只做
写显存这一件事。它排在 `APRIORI.inc` 里 `GraphicsConsoleDxe` 之前，而
APRIORI 条目启动时不评估 depex，所以它不依赖任何厂商 blob。

厂商的 `DisplayDxe` 和 `DisplayReEnablerDxe` 曾经被链接进来（即
`USE_CUSTOM_DISPLAY_DRIVER = 1`，lavender 在同款芯片上的选择），但在这个
单元上测出的结果相反：早期刻度带先出现、随后消失，背光却一直亮着——blob
接管了 MDSS，不再扫描我们写的那段窗口。同一块面板不能有两个主人，而这个
只负责写的更好预测。两者现在都不进卷，`proprietary-files.txt` 里保留
`O` 记录，`check-clover-uefi.py` 也会拦住把它们加回来的改动。

没有 GOP 时 `GraphicsConsoleDxe` 起不来，UniXNU 会退回串口文本控制台——
在平板上等于看不见，所以卷里必须有 `CloverGopDxe`，这条同样是检查项。

"屏幕上什么都没变"分不清是"我们的代码没跑"还是"跑了但没画"，所以启动链上
留了一串整屏纯色标记，后一个覆盖前一个，屏幕最后是什么颜色，就说明调度走到了哪一步：

- **红**：`BootShim` 在拷贝固件之前先把 ABL 正在扫描的整段窗口涂红。红色出现，
  说明 ABL 确实跳进了我们的镜像。
- **品红**：`CloverLadderEarly` 在 `APRIORI.inc` 第 23 行、紧跟 Pcd 之后，它被派发
  就说明 DXE dispatcher 已经进入 APRIORI 列表。
- **青**：`CloverLadderLate` 在第 56 行、紧跟 `ClockDxe` 之后 —— 青色说明
  `ClockDxe` 返回了。
- **黄**：`CloverLadderBds` 在第 79 行、`BdsDxe` 之前 —— 黄色说明上面的存储和
  variable 一整块（DiskIo 到 HiiDatabase）都返回了。
- **黑条**：尾部太长，一级一个颜色试不起。`CloverTail1`～`CloverTail9` 依次排在
  尾部九个分界之后，每个只在黄底上画一条黑横条（满宽、90 行高，行号
  120/320/520/720/920/1120/1320/1520/1720）。数清楚有几条，就知道 dispatcher
  过了第几个分界。
- **绿**：`CloverGopDxe`（第 141 行）发布 GOP 之后整屏涂绿——绿会一次盖掉所有
  黑条，那正是"整条尾巴都过了"的读法。`GraphicsConsoleDxe` 也就能起来。

UniXNU 菜单会盖掉绿色。于是：

| 屏幕 | 含义 |
| --- | --- |
| 一直停在 Mi 标志 | ABL 没有跳进 BootShim（镜像/启动流程问题），或一进去就挂了 |
| 红色 | DXE dispatcher 没走到 APRIORI 第 23 行：问题在 SEC/PEI 或 Pcd 之前 |
| 品红 | 卡在第 24～52 行：`EnvDxe`、各 arch 驱动、Qcom blob，或 `ClockDxe` 自己 |
| 青 | `ClockDxe` 已返回，卡在第 53～78 行：`DiskIo`、`Partition`、`SdccDxe`、`Fat`、`Variable`、`RTC`、`HiiDatabase` 这一段 |
| 黄，无黑条 | 存储和 variable 都过了，但 `BdsDxe` 自己的入口没返回 |
| 黄 + 1 条 | `BdsDxe` 返回了，卡在 `TLMM` 到 `UsbfnDwc3` 这一段厂商驱动 |
| 黄 + 2 条 | 卡在 `UsbBus`/`UsbKb`/`UsbMassStorage` |
| 黄 + 3 条 | 卡在 `UsbMsd`/`UsbDevice`/`UsbConfig`/`Buttons`/`Tsens` |
| 黄 + 4 条 | 卡在 `TzDxe` 自己 |
| 黄 + 5 条 | 卡在 `LimitsDxe` 自己 |
| 黄 + 6 条 | 卡在 `HashDxe` 自己 |
| 黄 + 7 条 | 卡在 `RngDxe` 自己 |
| 黄 + 8 条 | 卡在串口 console 栈：`SimpleTextInOutSerial`/`ConPlatform`/`ConSplitter` |
| 黄 + 9 条 | console 栈也过了，卡在 `CloverGopDxe` 自己（GOP 没发布） |
| 绿色 | GOP 已发布，问题在 BDS 之后：UniXNU 的启动项、payload 或应用本身 |
| 菜单 | Stage 1 达成 |

黑条只报"调度顺序走到了哪里"：`[Depex] TRUE` 的探针即使前面的驱动因依赖未满足
被跳过也会照常派发，所以条数不等于"这些驱动都成功了"，只等于"派发顺序已经越过
它们的边界还没卡住"。真正卡死会停在某个驱动入口里，后面的条就不会出现。

`BdsDxe` 自己进入 BDS 阶段不给颜色：它在这个 DXE 核里装的是 arch protocol，而
`CoreRegisterProtocolNotify` 不会为已存在的协议触发回调，那样的通知只在协议被
重装时才响，正常路径上永远不亮。黄色只说明它前面的驱动都返回了。

## ClockDxe 为什么要打补丁

本机固件卷里的 `ClockDxe` 在 SDM660 上会卡死在两处没有超时的硬件握手里：
一次 RCGR 更新（`MMCC + 0x2040`，`mdp_clk_src`）和一次 GDSC PWR_ON 等待。
DXE 调度是串行的，卡在 ClockDxe 就不再往下走，`CloverGopDxe` 也轮不到——
屏幕停在 BootShim 涂的红色上。

上游对同一个问题已经有定论：Project-Silicium/Device-Binaries 里
`ClockDxe.patched.efi` 与 stock `ClockDxe.efi` 只差 24 个字节，
全部是在时钟规划初始化里把六条 `BL` 换成 NOP，lavender 的 INF 直接引用
patched 文件。本机 stock blob 在这六个偏移上写着同样的指令字，所以这里照做：

```sh
python3 scripts/extract-clover-blobs.py --xbl <p-xbl.bin> --checkout ~/mu-clover
```

提取脚本会同时写出 stock `ClockDxe.efi`（留作对照）和
`ClockDxe.patched.efi`，并把 INF 的 `PE32` 指向后者。`check-clover-uefi.py`
会反过来验证 INF 确实引用了 patched 文件、且六个站点都已是 NOP。

## UniXNU 给 stock 设备包加了什么

gta4l 的 README 让你在每次检出更新后手改 DSC 和 `Include/DXE.inc`。
clover 则用同一个宏把三个模块收在一起：

```
!ifdef $(UNIXNU_BUILD)
  INF UniXNUPkg/Application/UniXNU/UniXNU.inf
  INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
  INF DarwinBootPkg/Driver/DarwinBoot.inf
!endif
```

`UniXNU-clover/board.toml` 在 `[firmware.defines]` 里设了
`UNIXNU_BUILD = "1"`，`firmware.py` 会把这张表变成 `-D` 参数。于是同一份检出
加这个叠加层，能用同一份 DSC 构建两种东西：普通 Android 固件
（`build_uefi.py -d clover`），以及 `./unixnu build firmware` 产出的 UniXNU 固件卷。
两个包根 `{tree}/package` 和 `{tree}/drivers/DarwinBoot` 由板级仓库通过
`[firmware] packages` 提供。

## 构建

macOS 无法直接构建（CLANGPDB 要对着 Linux 头文件交叉编译 AArch64 PE/COFF），
所以编译在 colima 下的 Linux 客户机里进行。

```sh
bash scripts/fetch-mu-silicium.sh ~/mu-clover   # 按固定 SHA 拉取，不带 --recursive
python3 scripts/apply-clover-overlay.py --uefi ~/mu-clover
bash scripts/build-clover-uefi.sh               # 配置客户机、套叠加层、构建
```

`fetch-mu-silicium.sh` 从父树的 `git submodule status` 里取每一个提交
——从不取分支名——并用 `git rev-parse HEAD` 核对每个检出，因为直连 GitHub
在这条网络上会卡住，而 `gh-proxy.com` 能按 SHA 应答。它还会再往下一层，
因为 mu_basecore 又内嵌了九个仓库。

`build-clover-uefi.sh` 在 colima 的 `clover` profile 下准备 Ubuntu 24.04 arm64
客户机，安装上游依赖，重新套一遍叠加层，把树 rsync 进客户机，填充 extdep 缓存，
跑 `stuart_update`，最后执行 `build_uefi.py -d clover`。`seed-clover-extdeps.py`
通过镜像逐个拉取 GitHub 上的 `ext_dep`，并核对描述文件里写的 sha256，把它填进
`STUART_EXTDEP_CACHE_PATH`——没有它，一次网络故障会以
"External Dependencies in the environment are out of date" 的形式出现。

推荐路径是板级仓库里的驱动：

```sh
cd ~/UniXNU
./unixnu build firmware --uefi ~/mu-clover --edk2 ~/mu-clover/Mu_Basecore --target RELEASE
./unixnu bootimg --ramdisk none -o ~/clover-out/clover-boot.img
```

`scripts/unixnu/firmware.py` 读取 `board.toml`，打开
`Resources/Configs/clover.toml` 查 `[uefi_fd]` 几何，把
`[firmware.defines]` 的每个键传成 `-D`，再以
`-p Platforms/Xiaomi/cloverPkg/clover.dsc` 调用 EDK II 的 `build`。
`bootimg` 编译检出里的 `BootShim/BootShim.S`，把它拼在固件卷前面，对这两段
gzip，然后追加板级 DTB——正是 stock ABL 期待的形状。它会核对 shim 的
Image Size 与 kernel 字段实际写入的字节数，所以本叠加层的 `BootShim.S` 写的是
`FD_SIZE + shim` 而不是 `FD_SIZE`。

`clover.toml` 里的 `[boot_image]` 是为独立构建路径准备的。`build_uefi.py`
只在 `[boot_image]` 的值非零/为真时才转发它，所以 `base` 没法设成 0，
mkbootimg 的默认值（2048 字节页、`0x10000000` base）会生效；所有 Mu 设备
都吃这个默认值，而且都是 header v1 或更新。clover 是 v0，所以真正上机的是
`./unixnu bootimg` 打出来的镜像：页 4096、base 0、stock 偏移。

## 检查

```sh
python3 scripts/check-clover-uefi.py                      # 离线
python3 scripts/check-clover-uefi.py --checkout ~/mu-clover
```

五组检查。`fv` 按 EDK II 预处理器的方式展开 `clover.fdf`，把每个 `INF` 和
`SECTION RAW` 与 `proprietary-files.txt` 双向核对。`blobs` 看真实检出，
包括 ClockDxe 是否链接 patched 文件、六个站点是否都是 NOP。`map` 解析
`MemoryMapLib.c`，除已记录的 IMEM 嵌套外任何重叠都算错。`board` 把几何钉死在
两个仓库之间：`[uefi_fd]` 大小、`UEFI FD` 行、ADT 的 `uefi_fd`、splash 窗口
对 `Display Reserved` 行、ADT 每个保留区对内存图、`header_version`、
`board.toml` 是否仍带 `UNIXNU_BUILD`，以及 `APRIORI.inc`/`DXE.inc` 里的每个
`INF` 是否也在 `clover.dsc` 里声明；三段阶梯标记与九条尾部黑条的先后顺序也在这里
钉死，还会核对每个 `CloverTailN.inf` 的 `-DCLOVER_TAIL_BAND` 是不是正好等于 N
（否则两条探针会画在同一行，白白藏掉一个分界）。`inf` 把本叠加层 INF 的每个
`[Protocols]` GUID 对它自己在 `[Packages]` 里列的 `.dec` 文件解析一遍。

它跑在系统自带的 macOS Python 3.9 上（`tomllib`、`tomli`，或内置的子集解析器）。

## 上机

有意义的测试是刷进分区后的冷启动，因为这条路径上 stock loader 会先画出 Mi
启动画面——之后任何接管屏幕的动作都无处可藏。`fastboot boot` 在这台平板上
从不画启动画面，所以它的黑屏不携带任何信息。

```sh
adb -s 81ffcaaa reboot bootloader
fastboot devices
fastboot flash boot  ~/clover-out/clover-boot.img
fastboot flash cache ~/UniXNU/out/clover/payload/payload.img
fastboot reboot
```

`cache` 上的 payload 就是 UniXNU 菜单读取的内容。`boot` 是 `mmcblk0p12`；
stock 内容在板级仓库里逐字节完整地存了一份：
`facts/81ffcaaa-20261022-210928/img/unixnu-boot.img`，bootloader 已解锁，
恢复只需一条命令：

```sh
fastboot flash boot ~/UniXNU-clover/facts/81ffcaaa-20261022-210928/img/unixnu-boot.img
```

卡死时按住电源键 + 音量减 10-20 秒即可恢复。

## 移植进度

对照官方指南的 bring-up 顺序（`unixnu.com/porting/bring-up`）：

| 阶段 | 状态 |
| --- | --- |
| UEFI 到达 BDS，且移植所需服务齐全 | `CloverGopDxe` 已发布 GOP；simple text in/out、串口、`SdccDxe` 提供的 `BlockIo`/`SimpleFileSystem`、FV2 与 variable 栈均由 APRIORI 启动。仍需一次真正把菜单显示到屏幕上的启动来确认 |
| UniXNU 菜单读取 payload 卷 | payload 已写入 `cache`；串口菜单可用，图形菜单等 GOP 实测 |
| payload 交接给 DarwinBoot | 本机未开始 |
| DarwinBoot 进入 XNU | 未开始 |
| 存储与 root 设备 | 未开始 |
| 用户态 | 未开始 |

从 `v0.3.3` 起，卷里不再链接厂商 `DisplayDxe` / `DisplayReEnablerDxe`。它们会
重编程 ABL 已经点亮并正在扫描的 MDSS 和面板，实测表现是刻度带先出现后消失、
背光常亮——两个面板主人互相打断。现在显示只有一个主人：ABL 留下的窗口和
只负责写的 `CloverGopDxe`。

`v0.3.0` 之前的固件带过一套调试仪器——checkpoint 刻度条、异常报告和定时器
PC 采样——用来找出 DXE 调度在这块板上停在哪里。那部分工作保留在 `v0.2.42`
标签上，结论写在板级仓库的 notes 里，不属于这次构建。

## 许可证

BSD-2-Clause-Patent，与 Mu-Silicium、UniXNU 和 UniXNU-sheng 一致。
