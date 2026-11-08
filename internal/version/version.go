// Package version holds the build version of Ailune.
package version

// Version is the semantic version reported by the CLI and the control API.
// It is intentionally a variable so releases can override it with -ldflags.
var Version = "0.1.0-dev"

// UserAgent is used for outbound HTTP requests made by the core.
var UserAgent = "Ailune/" + Version
