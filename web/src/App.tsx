import { useCallback, useEffect, useState } from 'react'

type WsMessage =
  | { type: 'hello'; message: string }
  | { type: 'alert'; fire: number; smoke: number; ts: number }

function buildWsUrl(): string {
  const explicit = import.meta.env.VITE_WS_URL as string | undefined
  if (explicit) {
    return explicit
  }
  const { protocol, hostname } = window.location
  const isHttps = protocol === 'https:'
  const wsProto = isHttps ? 'wss:' : 'ws:'
  if (import.meta.env.DEV) {
    return `${wsProto}//${hostname}:8000/ws`
  }
  return `${wsProto}//${window.location.host}/ws`
}

function playUrgentTone(): void {
  try {
    const ctx = new AudioContext()
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    o.type = 'sine'
    o.frequency.value = 880
    o.connect(g)
    g.connect(ctx.destination)
    g.gain.setValueAtTime(0.12, ctx.currentTime)
    g.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.35)
    o.start(ctx.currentTime)
    o.stop(ctx.currentTime + 0.35)
  } catch {
    /* ignore */
  }
}

function vibrateUrgent(): void {
  if (typeof navigator !== 'undefined' && navigator.vibrate) {
    navigator.vibrate([120, 80, 120, 80, 200])
  }
}

export default function App() {
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [urgent, setUrgent] = useState<{
    fire: number
    smoke: number
  } | null>(null)

  const dismissUrgent = useCallback(() => setUrgent(null), [])

  useEffect(() => {
    const url = buildWsUrl()
    const ws = new WebSocket(url)

    ws.onopen = () => {
      setConnected(true)
      setError(null)
    }

    ws.onclose = () => {
      setConnected(false)
    }

    ws.onerror = () => {
      setError(
        'Unable to reach the alert service. Check your connection and try again later.',
      )
    }

    ws.onmessage = (ev) => {
      let data: WsMessage
      try {
        data = JSON.parse(ev.data as string) as WsMessage
      } catch {
        return
      }
      if (data.type === 'alert') {
        setUrgent({ fire: data.fire, smoke: data.smoke })
        vibrateUrgent()
        playUrgentTone()
      }
    }

    return () => {
      ws.close()
    }
  }, [])

  const urgentKind =
    urgent && urgent.fire > 0 && urgent.smoke > 0
      ? 'both'
      : urgent && urgent.fire > 0
        ? 'fire'
        : urgent && urgent.smoke > 0
          ? 'smoke'
          : null

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">Safety alerts</h1>
        <p className="app__subtitle">
          Official hazard notifications for your area. Add this page to your
          home screen to get alerts like an app.
        </p>
      </header>

      <div className="status-row" aria-live="polite">
        <span
          className={`pill ${connected ? 'pill--ok' : 'pill--warn'}`}
          title="Link to notification service"
        >
          {connected ? '● Subscribed to alerts' : '○ Connecting…'}
        </span>
      </div>

      {error && (
        <p className="hint" role="alert">
          {error}
        </p>
      )}

      {connected && !error && (
        <p className="hint">
          You will only see a screen here when fire or smoke is detected by the
          monitoring system. Keep this page open or installed for the best
          chance of receiving a warning in time.
        </p>
      )}

      {urgent && urgentKind && (
        <div
          className="alert-backdrop"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="urgent-title"
          aria-describedby="urgent-desc"
        >
          <div
            className={`alert-panel ${
              urgentKind === 'smoke'
                ? 'alert-panel--smoke'
                : urgentKind === 'both'
                  ? 'alert-panel--both'
                  : ''
            }`}
          >
            <span className="alert-badge">Urgent — hazard reported</span>
            <h2 id="urgent-title" className="alert-title">
              {urgentKind === 'fire' && 'Fire reported'}
              {urgentKind === 'smoke' && 'Smoke reported'}
              {urgentKind === 'both' && 'Fire & smoke reported'}
            </h2>
            <p id="urgent-desc" className="alert-detail">
              The monitoring system has detected a possible hazard. Stay calm,
              follow local instructions, and move to safety if you are in the
              area.
              {urgent.fire > 0 && (
                <>
                  {' '}
                  Fire: {urgent.fire} instance{urgent.fire === 1 ? '' : 's'}.
                </>
              )}
              {urgent.smoke > 0 && (
                <>
                  {' '}
                  Smoke: {urgent.smoke} instance{urgent.smoke === 1 ? '' : 's'}.
                </>
              )}
            </p>
            <button
              type="button"
              className="btn alert-dismiss"
              onClick={dismissUrgent}
            >
              I understand
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
