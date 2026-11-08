//go:build !linux

package supervisor

import (
	"os/exec"
	"syscall"
)

func childProcAttr() *syscall.SysProcAttr { return nil }

func terminate(cmd *exec.Cmd) {
	if cmd.Process != nil {
		_ = cmd.Process.Signal(syscall.SIGTERM)
	}
}
