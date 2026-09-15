import '@testing-library/jest-dom/vitest'

afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
  window.history.replaceState(null, '', window.location.pathname)
})
