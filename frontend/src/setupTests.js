import '@testing-library/jest-dom'
import React from 'react'

jest.mock('react-markdown', () => {
  return function MockReactMarkdown({ children, components }) {
    return <div data-testid="markdown">{children}</div>
  }
})

jest.mock('remark-gfm', () => () => {})
