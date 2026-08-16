; -- MyBooks.iss --
#define MyAppName "MyBooks Service"
#define MyAppVersion "3.48.0"
#define MyAppPublisher "PoxenStudio"
#define MyAppExeName "MyBooks_Service"
#define TarFileName "mybooks_v" + MyAppVersion + ".tar"
#define IconFileName "mybooks.ico"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://mybooks.top
AppSupportURL=https://mybooks.top
AppUpdatesURL=https://mybooks.top
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=.\Output
OutputBaseFilename=MyBooks_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#IconFileName}

; 卸载时先执行自定义代码注销 WSL，再删除文件，防止文件被占用
UninstallFilesDir={app}
UninstallDisplayIcon={app}\{#IconFileName}


[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[CustomMessages]
english.StartMyBooksComment=Start the MyBooks server and open it in your browser
english.StopMyBooksComment=Stop the MyBooks server
english.RestartMyBooksComment=Restart (or start) the MyBooks server and open it in your browser
chinesesimplified.StartMyBooksComment=启动 MyBooks 服务，并在浏览器中打开
chinesesimplified.StopMyBooksComment=停止 MyBooks 服务
chinesesimplified.RestartMyBooksComment=重启（或启动）MyBooks 服务，并在浏览器中打开

[Files]
; 打包 Docker 导出的 tar 镜像文件
Source: "{#TarFileName}"; DestDir: "{app}"; Flags: ignoreversion

; 创建一个启动脚本 (替代 Docker run)
Source: "dummy.txt"; DestDir: "{app}"; DestName: "StartMyBooks.bat"; Flags: ignoreversion; AfterInstall: CreateStartBatch

; 创建一个停止脚本
Source: "dummy.txt"; DestDir: "{app}"; DestName: "StopMyBooks.bat"; Flags: ignoreversion; AfterInstall: CreateStopBatch

; 创建一个重启脚本 (未启动时则启动)
Source: "dummy.txt"; DestDir: "{app}"; DestName: "RestartMyBooks.bat"; Flags: ignoreversion; AfterInstall: CreateRestartBatch

Source: "{#IconFileName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 在桌面快捷方式中指定图标
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\StartMyBooks.bat"; WorkingDir: "{app}"; IconFilename: "{app}\{#IconFileName}"; Comment: "{cm:StartMyBooksComment}"

; 在开始菜单快捷方式中指定图标
Name: "{group}\{#MyAppName}"; Filename: "{app}\StartMyBooks.bat"; WorkingDir: "{app}"; IconFilename: "{app}\{#IconFileName}"; Comment: "{cm:StartMyBooksComment}"

; 开始菜单中的停止服务快捷方式
Name: "{group}\Stop {#MyAppName}"; Filename: "{app}\StopMyBooks.bat"; WorkingDir: "{app}"; IconFilename: "{app}\{#IconFileName}"; Comment: "{cm:StopMyBooksComment}"

; 开始菜单中的重启服务快捷方式
Name: "{group}\Restart {#MyAppName}"; Filename: "{app}\RestartMyBooks.bat"; WorkingDir: "{app}"; IconFilename: "{app}\{#IconFileName}"; Comment: "{cm:RestartMyBooksComment}"

; 开始菜单中的卸载快捷方式 (通常使用系统默认图标，也可指定)
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; IconFilename: "{app}\{#IconFileName}"


[Dirs]
; 创建用于持久化书库数据的目录，启动时绑定挂载到容器内的 /data
; 卸载时不删除该目录，避免误删用户书库数据
Name: "{app}\data"; Flags: uninsneveruninstall


[Run]
; 关闭当前 WSL2 虚拟机（如果有其他发行版在运行也会一并停止），确保随后导入的 MyBooksService
; 是在应用了 EnsureWslMirroredNetworking 写入的新 .wslconfig 设置之后才第一次启动
Filename: "wsl.exe"; Parameters: "--shutdown"; Flags: runhidden waituntilterminated; StatusMsg: "正在应用 WSL 网络配置..."

; 安装完成后，自动导入 WSL 实例
; 参数说明: --import <发行版名称> <安装目录> <tar文件路径> --version 2
Filename: "wsl.exe"; Parameters: "--import MyBooksService ""{app}\wsl_data"" ""{app}\{#TarFileName}"" --version 2"; Flags: runhidden waituntilterminated; StatusMsg: "正在初始化 MyBooks 运行环境..."

[UninstallRun]
; 卸载时，首先注销 WSL 实例，释放 ext4.vhdx 文件占用
Filename: "wsl.exe"; Parameters: "--unregister MyBooksService"; Flags: runhidden waituntilterminated; StatusMsg: "正在清理 MyBooks 运行环境..."

[Code]
// 将 Windows 路径转换为 WSL (DrvFs) 下可访问的路径，例如 C:\Users\foo\bar -> /mnt/c/Users/foo/bar
function GetWslPath(WinPath: String): String;
var
  Drive: String;
  Rest: String;
begin
  Drive := Lowercase(Copy(WinPath, 1, 1));
  Rest := Copy(WinPath, 3, MaxInt);
  StringChangeEx(Rest, '\', '/', True);
  Result := '/mnt/' + Drive + Rest;
end;

// 确保 %USERPROFILE%\.wslconfig 中启用了让局域网 IP 可以访问 WSL 内服务所需的设置。
// .wslconfig 是标准 ini 格式，用 SetIniString 只增改这几个 key，不影响用户已有的其他设置/发行版配置。
// 三项设置缺一不可（均已在实测环境中验证过）：
//   [wsl2] networkingMode=mirrored   -- WSL 与主机共享网络接口，取代默认的 NAT 私有网络，
//                                       否则 Windows 的 localhost 转发只代理 127.0.0.1，不代理主机的局域网 IP
//   [wsl2] firewall=false            -- 镜像网络模式会额外启用一层 Hyper-V 防火墙，
//                                       默认只放行 ICMP/mDNS 等少量协议，会挡住 HTTP 等入站连接
//   [experimental] hostAddressLoopback=true -- 允许"主机自己"通过镜像 IP 回环访问 WSL 内的服务，
//                                       默认这个场景是不通的（局域网内其他设备访问则不受影响）
// 注意：这是按用户（USERPROFILE）级别的全局设置，会影响这台机器上所有 WSL 发行版，不仅仅是 MyBooksService。
// 另外，如果用户开启了经典 Windows 防火墙，还需要放行对应端口的入站连接（New-NetFirewallRule），
// 这一步涉及管理员权限，未包含在此安装程序中，遇到局域网仍无法访问时需要用户手动添加。
procedure EnsureWslMirroredNetworking();
var
  WslConfigPath: String;
begin
  WslConfigPath := ExpandConstant('{%USERPROFILE}\.wslconfig');
  SetIniString('wsl2', 'networkingMode', 'mirrored', WslConfigPath);
  SetIniString('wsl2', 'firewall', 'false', WslConfigPath);
  SetIniString('experimental', 'hostAddressLoopback', 'true', WslConfigPath);
end;

// 安装步骤完成后（文件已复制，尚未执行 [Run] 里的 wsl --shutdown / --import），
// 先写好 .wslconfig，确保 MyBooksService 首次启动时就已经是镜像网络模式
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    EnsureWslMirroredNetworking();
  end;
end;

// 动态生成启动批处理文件，避免额外携带文件
procedure CreateStartBatch();
var
  BatchFile: String;
  BatchContent: String;
  DataPath: String;
begin
  BatchFile := ExpandConstant('{app}\StartMyBooks.bat');
  DataPath := GetWslPath(ExpandConstant('{app}\data'));

  // 在独立窗口中以前台方式运行服务（保留日志输出），主窗口等待片刻后打开默认浏览器
  // 启动前先将本机的 data 目录绑定挂载到容器内的 /data，实现书库数据持久化到本机
  BatchContent := '@echo off' + #13#10 +
                  'echo 正在启动 MyBooks...' + #13#10 +
                  'start "MyBooks Server" wsl.exe -d MyBooksService -u root -- bash -c "export PGID=1000 && export PUID=1000 && mkdir -p /data && (grep -qs \" /data \" /proc/mounts || mount --bind \"' + DataPath + '\" /data); /var/www/mybooks/docker/start.sh"' + #13#10 +
                  'echo 正在等待服务就绪...' + #13#10 +
                  'timeout /t 5 /nobreak >nul' + #13#10 +
                  'start "" "http://localhost"' + #13#10 +
                  'echo.' + #13#10 +
                  'echo MyBooks 已启动，可以在浏览器中使用 http://<本机IP> 访问。服务日志显示在另一个窗口中。' + #13#10 +
                  'echo 关闭此窗口不会停止服务，如需停止请使用 Stop MyBooks。' + #13#10 +
                  'echo 按任意键关闭此窗口...' + #13#10 +
                  'pause >nul';

  SaveStringToFile(BatchFile, BatchContent, False);
end;

// 动态生成停止批处理文件
procedure CreateStopBatch();
var
  BatchFile: String;
  BatchContent: String;
begin
  BatchFile := ExpandConstant('{app}\StopMyBooks.bat');

  BatchContent := '@echo off' + #13#10 +
                  'echo 正在停止 MyBooks...' + #13#10 +
                  'wsl.exe --terminate MyBooksService' + #13#10 +
                  'echo.' + #13#10 +
                  'echo MyBooks 已停止。按任意键关闭此窗口...' + #13#10 +
                  'pause >nul';

  SaveStringToFile(BatchFile, BatchContent, False);
end;

// 动态生成重启批处理文件：未启动时启动，已启动时重启
procedure CreateRestartBatch();
var
  BatchFile: String;
  BatchContent: String;
  DataPath: String;
begin
  BatchFile := ExpandConstant('{app}\RestartMyBooks.bat');
  DataPath := GetWslPath(ExpandConstant('{app}\data'));

  // 先尝试注销 WSL 实例（未运行时为空操作），再重新启动，统一处理“启动”和“重启”两种场景
  // 启动前先将本机的 data 目录绑定挂载到容器内的 /data，实现书库数据持久化到本机
  BatchContent := '@echo off' + #13#10 +
                  'echo 正在重启 MyBooks...' + #13#10 +
                  'wsl.exe --terminate MyBooksService >nul 2>&1' + #13#10 +
                  'timeout /t 2 /nobreak >nul' + #13#10 +
                  'wsl.exe -d MyBooksService -u root -- bash -c "export PGID=1000 && export PUID=1000 && mkdir -p /data && (grep -qs \" /data \" /proc/mounts || mount --bind \"' + DataPath + '\" /data); /var/www/mybooks/docker/start.sh"' + #13#10 +
                  'echo.' + #13#10 +
                  'echo MyBooks 已启动，按任意键关闭此窗口...' + #13#10 +
                  'pause >nul';

  SaveStringToFile(BatchFile, BatchContent, False);
end;

// 安装前检查 WSL 是否可用
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  // 简单检查 wsl.exe 是否存在且能执行
  if not Exec('wsl.exe', '--status', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if MsgBox('未检测到 Windows 子系统 for Linux (WSL)。' + #13#10 +
              '本程序依赖 WSL2 运行。是否现在尝试通过 Windows 功能启用它？' + #13#10 +
              '(可能需要重启电脑)', mbConfirmation, MB_YESNO) = IDYES then
    begin
      Exec('wsl.exe', '--install', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
      MsgBox('WSL 安装已触发。请重启电脑后，再次运行本安装程序。', mbInformation, MB_OK);
      Result := False;
    end
    else
    begin
      Result := False;
    end;
  end;
end;

// 卸载时确保先注销 WSL，防止文件被占用导致删除失败
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    // 静默注销 WSL 实例
    Exec('wsl.exe', '--unregister MyBooksService', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;