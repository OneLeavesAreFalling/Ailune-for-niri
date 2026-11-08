package httpapi

import "runtime"

func runtimeVersion() string { return runtime.Version() }
