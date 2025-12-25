const { app, BrowserWindow, Menu, Tray } = require('electron')
const path = require('path')
const url = require('url')

let mainWindow
let tray = null

// 创建窗口函数
function createWindow() {
  // 创建浏览器窗口
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: 'Talebook',
    icon: path.join(__dirname, '../public/logo/favicon.ico'),
    webPreferences: {
      // 禁用nodeIntegration以提高安全性
      nodeIntegration: false,
      // 启用contextIsolation以提高安全性
      contextIsolation: true,
      // 禁用enableRemoteModule以提高安全性
      enableRemoteModule: false,
    }
  })

  // 加载应用
  if (process.env.NODE_ENV === 'development') {
    // 开发环境下加载本地开发服务器
    mainWindow.loadURL('http://localhost:9000')
    // 打开开发者工具
    mainWindow.webContents.openDevTools()
  } else {
    // 生产环境下加载打包后的静态文件
    mainWindow.loadURL(url.format({
      pathname: path.join(__dirname, '../dist/index.html'),
      protocol: 'file:',
      slashes: true
    }))
  }

  // 窗口关闭事件
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // 创建应用菜单
  createMenu()
}

// 创建应用菜单
function createMenu() {
  const template = [
    {
      label: '文件',
      submenu: [
        {
          label: '退出',
          accelerator: process.platform === 'darwin' ? 'Command+Q' : 'Ctrl+Q',
          click() {
            app.quit()
          }
        }
      ]
    },
    {
      label: '编辑',
      submenu: [
        { label: '撤销', accelerator: 'CmdOrCtrl+Z', role: 'undo' },
        { label: '重做', accelerator: 'Shift+CmdOrCtrl+Z', role: 'redo' },
        { type: 'separator' },
        { label: '剪切', accelerator: 'CmdOrCtrl+X', role: 'cut' },
        { label: '复制', accelerator: 'CmdOrCtrl+C', role: 'copy' },
        { label: '粘贴', accelerator: 'CmdOrCtrl+V', role: 'paste' },
        { label: '全选', accelerator: 'CmdOrCtrl+A', role: 'selectAll' }
      ]
    },
    {
      label: '视图',
      submenu: [
        { label: '刷新', accelerator: 'CmdOrCtrl+R', click() { mainWindow.reload() } },
        { label: '开发者工具', accelerator: process.platform === 'darwin' ? 'Alt+Command+I' : 'Ctrl+Shift+I', click() { mainWindow.webContents.openDevTools() } }
      ]
    }
  ]

  const menu = Menu.buildFromTemplate(template)
  Menu.setApplicationMenu(menu)
}

// 应用就绪事件
app.on('ready', () => {
  createWindow()
  // 创建系统托盘
  createTray()
})

// 创建系统托盘
function createTray() {
  if (process.platform === 'darwin') return // macOS不使用系统托盘

  tray = new Tray(path.join(__dirname, '../public/logo/favicon.ico'))
  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click() {
        mainWindow.show()
      }
    },
    {
      label: '退出',
      click() {
        app.quit()
      }
    }
  ])
  tray.setToolTip('Talebook')
  tray.setContextMenu(contextMenu)
  tray.on('click', () => {
    mainWindow.show()
  })
}

// 所有窗口关闭事件
app.on('window-all-closed', () => {
  // 在macOS上，除非用户用Cmd+Q明确退出，否则绝大部分应用及其菜单栏会保持激活
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// 应用激活事件
app.on('activate', () => {
  // 在macOS上，当点击dock图标并且没有其他窗口打开时，通常会在应用中重新创建一个窗口
  if (mainWindow === null) {
    createWindow()
  }
})
