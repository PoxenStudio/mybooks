// filepath: src/plugins/dark-mode.js
export default () => {
    if (process.client) {
      const darkModeEnabled = localStorage.getItem('darkMode') === 'true';
      if (darkModeEnabled) {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    }
};