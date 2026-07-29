/**
 * 곁눈(Gyeotnun) 진입점
 * 팀 Second Look
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

// PWA 설치 요건(manifest + service worker) 충족. HTTPS(또는 localhost)에서만 등록된다 -
// registration 자체가 실패해도(HTTP 배포 등) 앱 동작에는 영향이 없다.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
