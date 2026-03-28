import { useCallback, useEffect, useState } from 'react'

type WsMessage =
  | { type: 'hello'; message: string }
  | { type: 'alert'; fire: number; smoke: number; ts: number; source?: string }

type LogEvent = {
  ts: number
  iso: string
  fire: number
  smoke: number
  source: string
  summary: string
}

function apiBase(): string {
  const b = import.meta.env.VITE_API_BASE as string | undefined
  if (b) {
    return b.replace(/\/$/, '')
  }
  if (import.meta.env.DEV) {
    return 'http://localhost:8000'
  }
  return ''
}

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

async function fetchEventLog(limit = 40): Promise<LogEvent[]> {
  const base = apiBase()
  const res = await fetch(`${base}/api/events?limit=${limit}`)
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`)
  }
  const data = (await res.json()) as { events: LogEvent[] }
  return data.events ?? []
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
  const [logError, setLogError] = useState<string | null>(null)
  const [events, setEvents] = useState<LogEvent[]>([])
  const [urgent, setUrgent] = useState<{
    fire: number
    smoke: number
  } | null>(null)

  const dismissUrgent = useCallback(() => setUrgent(null), [])

  const refreshLog = useCallback(async () => {
    try {
      const list = await fetchEventLog()
      setEvents(list)
      setLogError(null)
    } catch {
      setLogError('Could not load the detection log.')
    }
  }, [])

  useEffect(() => {
    void refreshLog()
    const id = window.setInterval(() => void refreshLog(), 12_000)
    return () => window.clearInterval(id)
  }, [refreshLog])

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
        void refreshLog()
      }
    }

    return () => {
      ws.close()
    }
  }, [refreshLog])

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
          The desktop monitoring app detects fire and smoke. This page loads the
          shared log and shows an urgent notice when a new hazard is reported.
        </p>
      </header>

      <div className="status-row" aria-live="polite">
        <span
          className={`pill ${connected ? 'pill--ok' : 'pill--warn'}`}
          title="Live alert channel"
        >
          {connected ? '● Live alerts connected' : '○ Connecting…'}
        </span>
      </div>

      {error && (
        <p className="hint" role="alert">
          {error}
        </p>
      )}

      <section className="log-section" aria-labelledby="log-heading">
        <h2 id="log-heading">Detection log</h2>
        {logError && (
          <p className="hint" role="status">
            {logError}
          </p>
        )}
        {events.length === 0 && !logError ? (
          <p className="log-empty">
            No hazard entries yet. When the desktop app sees fire or smoke, they
            appear here.
          </p>
        ) : (
          <ul className="log-list">
            {events.map((e, i) => (
              <li key={`${e.ts}-${i}-${e.summary}`} className="log-item">
                <time dateTime={e.iso}>{e.iso.replace('T', ' ').replace('Z', ' UTC')}</time>
                <strong>{e.summary}</strong>
                <span>({e.source.replace('_', ' ')})</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {connected && !error && (
        <p className="hint">
          Keep this page open or install it. Alerts also arrive instantly over the
          live connection when the desktop app reports a detection.
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
