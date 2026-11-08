//go:build linux

package supervisor

import (
	"os/exec"
	"syscall"
	"time"
)

func childProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setpgid: true}
}

func terminate(cmd *exec.Cmd) {
	if cmd.Process == nil {
		return
	}
	// Signal the process group so wrappers and their children exit together.
	pgid, err := syscall.Getpgid(cmd.Process.Pid)
	if err == nil {
		_ = syscall.Kill(-pgid, syscall.SIGTERM)
	} else {
		_ = cmd.Process.Signal(syscall.SIGTERM)
	}
	time.AfterFunc(3*time.Second, func() {
		if pgid, err := syscall.Getpgid(cmd.Process.Pid); err == nil {
			_ = syscall.Kill(-pgid, syscall.SIGKILL)
		}
	})
}
