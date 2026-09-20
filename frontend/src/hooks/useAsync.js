import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Run an async loader and expose {data, error, loading, reload}. `deps` re-run the loader;
 * `interval` (ms) polls while `shouldPoll(data)` returns true.
 */
export function useAsync(loader, deps = [], { interval, shouldPoll } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const version = useRef(0)

  const run = useCallback(
    async (silent = false) => {
      const v = ++version.current
      if (!silent) setState((s) => ({ ...s, loading: true, error: null }))
      try {
        const data = await loader()
        if (v === version.current) setState({ data, error: null, loading: false })
        return data
      } catch (error) {
        if (v === version.current) setState((s) => ({ data: s.data, error, loading: false }))
        return undefined
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    deps,
  )

  useEffect(() => {
    run()
  }, [run])

  useEffect(() => {
    if (!interval) return undefined
    if (shouldPoll && !shouldPoll(state.data)) return undefined
    const id = setInterval(() => run(true), interval)
    return () => clearInterval(id)
  }, [interval, shouldPoll, state.data, run])

  return { ...state, reload: run }
}
