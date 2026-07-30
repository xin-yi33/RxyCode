import React, { Component, ErrorInfo, ReactNode } from 'react';
import { Box, Text } from 'ink';
import { logError } from '../log.js';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error Boundary - catches rendering errors and shows a fallback UI.
 * Prevents the entire app from crashing on component errors.
 * 
 * Vercel React Best Practice: Always wrap top-level components
 * in error boundaries for graceful degradation.
 */
export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Log error to file via backend /log endpoint
    logError('React error boundary caught', {
      error: error.message,
      stack: error.stack?.slice(0, 500),
      componentStack: errorInfo.componentStack?.slice(0, 500),
    });
    // Log error to console in development
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <Box flexDirection="column" padding={1}>
          <Text color="#EF5350" bold>Rendering Error</Text>
          <Text color="#888">{this.state.error?.message || 'Unknown error'}</Text>
          <Text color="#666">Press Ctrl+C to exit, then restart RxyCode</Text>
        </Box>
      );
    }
    return this.props.children;
  }
}
