// Package auth provides the feature-standards browser-session HTTP handler and
// atomic memory/PostgreSQL storage boundaries. LoadConfig validates environment
// settings, NewServer opens the selected store, and Server.CurrentUser protects
// consumer read routes. Close the Server during application shutdown.
package auth
