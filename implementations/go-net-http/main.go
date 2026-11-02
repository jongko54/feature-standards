package main

import (
	"context"
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jongko54/feature-standards/implementations/go-net-http/auth"
)

func main() {
	config, err := auth.LoadConfig()
	if err != nil {
		log.Fatal(err)
	}
	app, err := auth.NewServer(config)
	if err != nil {
		log.Fatal("could not initialize authentication server")
	}
	defer app.Close()
	config.Password, config.DatabaseURL = "", ""
	server := &http.Server{
		Addr:              net.JoinHostPort(config.Host, config.Port),
		Handler:           app,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      15 * time.Second,
		IdleTimeout:       30 * time.Second,
		MaxHeaderBytes:    16 * 1024,
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Printf("go-net-http listening on %s (%s store)", server.Addr, config.Store)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
