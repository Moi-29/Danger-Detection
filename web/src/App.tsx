import { useCallback, useEffect, useRef, useState } from 'react'

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

type Screen = 'alerts' | 'settings'

const STORAGE_SOUND = 'danger-alerts-sound'
const STORAGE_VIBRATION = 'danger-alerts-vibration'

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

function loadBool(key: string, defaultVal: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    if (v === null) {
      return defaultVal
    }
    return v === '1' || v === 'true'
  } catch {
    return defaultVal
  }
}

function saveBool(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* ignore */
  }
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

function IconBell() {
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.89 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"
      />
    </svg>
  )
}

function IconSettings() {
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"
      />
    </svg>
  )
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('alerts')
  const [soundEnabled, setSoundEnabled] = useState(() =>
    loadBool(STORAGE_SOUND, true),
  )
  const [vibrationEnabled, setVibrationEnabled] = useState(() =>
    loadBool(STORAGE_VIBRATION, true),
  )
  const soundRef = useRef(soundEnabled)
  const vibrationRef = useRef(vibrationEnabled)
  soundRef.current = soundEnabled
  vibrationRef.current = vibrationEnabled

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
    saveBool(STORAGE_SOUND, soundEnabled)
  }, [soundEnabled])

  useEffect(() => {
    saveBool(STORAGE_VIBRATION, vibrationEnabled)
  }, [vibrationEnabled])

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
        if (vibrationRef.current) {
          vibrateUrgent()
        }
        if (soundRef.current) {
          playUrgentTone()
        }
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

  const nav = (
    <>
      <button
        type="button"
        className={`nav-item ${screen === 'alerts' ? 'nav-item--active' : ''}`}
        onClick={() => setScreen('alerts')}
        aria-current={screen === 'alerts' ? 'page' : undefined}
      >
        <IconBell />
        <span>Alerts</span>
      </button>
      <button
        type="button"
        className={`nav-item ${screen === 'settings' ? 'nav-item--active' : ''}`}
        onClick={() => setScreen('settings')}
        aria-current={screen === 'settings' ? 'page' : undefined}
      >
        <IconSettings />
        <span>Settings</span>
      </button>
    </>
  )

  return (
    <div className="shell">
      <aside className="shell__sidebar" aria-label="Main navigation">
        <div className="shell__brand">
          <span className="shell__brand-mark" aria-hidden="true" />
          <div>
            <div className="shell__brand-title">Safety alerts</div>
            <div className="shell__brand-tag">Hazard notifications</div>
          </div>
        </div>
        <nav className="shell__sidebar-nav">{nav}</nav>
      </aside>

      <div className="shell__main">
        {screen === 'alerts' && (
          <main className="screen" id="main" aria-labelledby="alerts-heading">
            <header className="screen__header">
              <h1 id="alerts-heading" className="screen__title">
                Alerts
              </h1>
              <p className="screen__lede">
                Live fire and smoke detections from the monitoring app.
              </p>
            </header>

            <div className="status-row" aria-live="polite">
              <span
                className={`pill ${connected ? 'pill--ok' : 'pill--warn'}`}
                title="Live alert channel"
              >
                {connected ? '● Live' : '○ Connecting'}
              </span>
            </div>

            {error && (
              <p className="banner banner--error" role="alert">
                {error}
              </p>
            )}

            <section className="card" aria-labelledby="log-heading">
              <h2 id="log-heading" className="card__title">
                Detection log
              </h2>
              {logError && (
                <p className="hint" role="status">
                  {logError}
                </p>
              )}
              {events.length === 0 && !logError ? (
                <p className="log-empty">
                  No hazard entries yet. When the desktop app sees fire or
                  smoke, they appear here.
                </p>
              ) : (
                <ul className="log-list">
                  {events.map((e, i) => (
                    <li
                      key={`${e.ts}-${i}-${e.summary}`}
                      className="log-item"
                    >
                      <time dateTime={e.iso}>
                        {e.iso.replace('T', ' ').replace('Z', ' UTC')}
                      </time>
                      <strong>{e.summary}</strong>
                      <span>({e.source.replace('_', ' ')})</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {connected && !error && (
              <p className="hint hint--footer">
                Keep this page open or install it. New alerts arrive instantly
                over the live connection.
              </p>
            )}
          </main>
        )}

        {screen === 'settings' && (
          <main className="screen" id="main" aria-labelledby="settings-heading">
            <header className="screen__header">
              <h1 id="settings-heading" className="screen__title">
                Settings
              </h1>
              <p className="screen__lede">
                Notifications and connection details for this device.
              </p>
            </header>

            <section className="card">
              <h2 className="card__title">Connection</h2>
              <p className="settings-row">
                <span className="settings-label">Live channel</span>
                <span
                  className={`pill ${connected ? 'pill--ok' : 'pill--warn'}`}
                >
                  {connected ? 'Connected' : 'Disconnected'}
                </span>
              </p>
              {error && (
                <p className="banner banner--error banner--tight" role="alert">
                  {error}
                </p>
              )}
            </section>

            <section className="card">
              <h2 className="card__title">When an alert arrives</h2>
              <label className="toggle">
                <span className="toggle__text">
                  <span className="toggle__label">Sound</span>
                  <span className="toggle__hint">Short tone on new hazard</span>
                </span>
                <input
                  type="checkbox"
                  className="toggle__input"
                  checked={soundEnabled}
                  onChange={(e) => setSoundEnabled(e.target.checked)}
                />
                <span className="toggle__switch" aria-hidden="true" />
              </label>
              <label className="toggle">
                <span className="toggle__text">
                  <span className="toggle__label">Vibration</span>
                  <span className="toggle__hint">Pattern on supported devices</span>
                </span>
                <input
                  type="checkbox"
                  className="toggle__input"
                  checked={vibrationEnabled}
                  onChange={(e) => setVibrationEnabled(e.target.checked)}
                />
                <span className="toggle__switch" aria-hidden="true" />
              </label>
            </section>

            <section className="card">
              <h2 className="card__title">Log</h2>
              <p className="hint">
                The list refreshes automatically about every 12 seconds. You can
                refresh immediately below.
              </p>
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void refreshLog()}
              >
                Refresh detection log
              </button>
            </section>

            <section className="card card--muted">
              <h2 className="card__title">About</h2>
              <p className="about-text">
                This app shows public hazard notifications when the desktop
                monitoring system reports fire or smoke. Install it to your home
                screen for quicker access.
              </p>
            </section>
          </main>
        )}
      </div>

      <nav className="shell__bottom" aria-label="Main navigation">
        {nav}
      </nav>

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
