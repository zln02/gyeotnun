/**
 * 곁눈(Gyeotnun) 진입점
 * 팀 Second Look
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { loadErrorCodes } from './errorCodes.js'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

// 오류 코드 표를 미리 받아 둔다(비차단) - 나중에 순수 클라이언트 오류(네트워크
// 끊김 등)가 나도 서버를 다시 부르지 않고 바로 안내 문구를 채울 수 있다.
loadErrorCodes()

// PWA 설치 요건(manifest + service worker) 충족. HTTPS(또는 localhost)에서만 등록된다 -
// registration 자체가 실패해도(HTTP 배포 등) 앱 동작에는 영향이 없다.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
