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

async function clearEventLog(): Promise<void> {
  const base = apiBase()
  // POST avoids 405 from some PWA service workers / static hosts that mishandle DELETE.
  const res = await fetch(`${base}/api/events/clear`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`)
  }
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

function IconRefresh({ spinning }: { spinning?: boolean }) {
  return (
    <svg
      className={`alerts-refresh-icon ${spinning ? 'alerts-refresh-icon--spin' : ''}`}
      viewBox="0 0 24 24"
      width="18"
      height="18"
      aria-hidden="true"
    >
      <path
        fill="currentColor"
        d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"
      />
    </svg>
  )
}

function IconEmptyCalm() {
  return (
    <svg
      className="alerts-empty__svg"
      viewBox="0 0 80 80"
      aria-hidden="true"
    >
      <circle
        cx="40"
        cy="40"
        r="34"
        fill="none"
        stroke="rgba(31, 107, 58, 0.35)"
        strokeWidth="2"
      />
      <path
        fill="none"
        stroke="rgba(143, 212, 164, 0.75)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M24 42l12 12 20-22"
      />
    </svg>
  )
}

function formatLogTime(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) {
      return iso
    }
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function formatSourceLabel(source: string): string {
  return source.replace(/_/g, ' ')
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
  const [logRefreshing, setLogRefreshing] = useState(false)
  const [clearingLog, setClearingLog] = useState(false)
  const [urgent, setUrgent] = useState<{
    fire: number
    smoke: number
  } | null>(null)

  const dismissUrgent = useCallback(() => setUrgent(null), [])

  const fetchLog = useCallback(async () => {
    try {
      const list = await fetchEventLog()
      setEvents(list)
      setLogError(null)
    } catch {
      setLogError('Could not load the detection log.')
    }
  }, [])

  const refreshLog = useCallback(async () => {
    setLogRefreshing(true)
    try {
      await fetchLog()
    } finally {
      setLogRefreshing(false)
    }
  }, [fetchLog])

  const clearHistory = useCallback(async () => {
    if (events.length === 0) {
      return
    }
    const ok = window.confirm(
      'Clear all hazard entries from this list? This removes them on the server for everyone using this alert service.',
    )
    if (!ok) {
      return
    }
    setClearingLog(true)
    try {
      await clearEventLog()
      setEvents([])
      setLogError(null)
    } catch {
      setLogError('Could not clear the detection log.')
    } finally {
      setClearingLog(false)
    }
  }, [events.length])

  useEffect(() => {
    void fetchLog()
    const id = window.setInterval(() => void fetchLog(), 12_000)
    return () => window.clearInterval(id)
  }, [fetchLog])

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
        void fetchLog()
      }
    }

    return () => {
      ws.close()
    }
  }, [fetchLog])

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
          <main
            className="screen screen--alerts"
            id="main"
            aria-labelledby="alerts-heading"
          >
            <header className="alerts-top">
              <div className="alerts-top__intro">
                <h1 id="alerts-heading" className="screen__title">
                  Alerts
                </h1>
                <p className="screen__lede">
                  Fire and smoke events from the desktop monitor, with instant
                  push when you keep this page open.
                </p>
              </div>
              <button
                type="button"
                className="btn btn--alerts-refresh"
                onClick={() => void refreshLog()}
                disabled={logRefreshing}
                aria-busy={logRefreshing}
                aria-label="Refresh detection log"
              >
                <IconRefresh spinning={logRefreshing} />
                <span>Refresh</span>
              </button>
            </header>

            <div
              className={`alerts-live ${connected ? 'alerts-live--on' : ''}`}
              aria-live="polite"
            >
              <div className="alerts-live__row">
                <span
                  className="alerts-live__dot"
                  aria-hidden="true"
                  data-on={connected}
                />
                <div className="alerts-live__text">
                  <span className="alerts-live__label">Live channel</span>
                  <span className="alerts-live__state">
                    {connected
                      ? 'Connected — new hazards appear here immediately'
                      : 'Connecting to alert service…'}
                  </span>
                </div>
              </div>
            </div>

            {error && (
              <p className="banner banner--error alerts-banner" role="alert">
                {error}
              </p>
            )}

            <section
              className="alerts-log-block"
              aria-labelledby="log-heading"
            >
              <div className="alerts-log-block__head">
                <h2 id="log-heading" className="alerts-log-block__title">
                  Recent activity
                </h2>
                <div className="alerts-log-block__toolbar">
                  <span className="alerts-log-block__count" aria-live="polite">
                    {events.length === 0
                      ? 'No entries'
                      : `${events.length} ${events.length === 1 ? 'entry' : 'entries'}`}
                  </span>
                  <button
                    type="button"
                    className="btn btn--clear-history"
                    onClick={() => void clearHistory()}
                    disabled={events.length === 0 || clearingLog}
                    aria-busy={clearingLog}
                    title="Remove all entries from the server log"
                  >
                    Clear list
                  </button>
                </div>
              </div>

              <div className="alerts-log-block__body">
                {logError && (
                  <p className="alerts-log-error" role="status">
                    {logError}
                  </p>
                )}
                {events.length > 0 && (
                  <ul className="alerts-log-list">
                    {events.map((e, i) => (
                      <li
                        key={`${e.ts}-${i}-${e.summary}`}
                        className="alerts-log-entry"
                      >
                        <div className="alerts-log-entry__meta">
                          <time
                            className="alerts-log-entry__time"
                            dateTime={e.iso}
                          >
                            {formatLogTime(e.iso)}
                          </time>
                          <span className="alerts-log-entry__source">
                            {formatSourceLabel(e.source)}
                          </span>
                        </div>
                        <p className="alerts-log-entry__summary">{e.summary}</p>
                        {(e.fire > 0 || e.smoke > 0) && (
                          <div className="alerts-log-entry__chips">
                            {e.fire > 0 && (
                              <span className="chip chip--fire">
                                Fire ×{e.fire}
                              </span>
                            )}
                            {e.smoke > 0 && (
                              <span className="chip chip--smoke">
                                Smoke ×{e.smoke}
                              </span>
                            )}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {events.length === 0 && !logError && (
                  <div className="alerts-empty">
                    <IconEmptyCalm />
                    <h3 className="alerts-empty__title">No hazards logged yet</h3>
                    <p className="alerts-empty__text">
                      When the monitoring app detects fire or smoke, each event
                      shows up here with a timestamp and source.
                    </p>
                  </div>
                )}
              </div>
            </section>

            {connected && !error && (
              <footer className="alerts-footer">
                <p className="alerts-footer__text">
                  Tip: add this app to your home screen for quicker access. The
                  log also refreshes in the background about every 12 seconds.
                </p>
              </footer>
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
