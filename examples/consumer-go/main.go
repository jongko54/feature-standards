package main

import (
	"context"
	"encoding/json"
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

func newHandler(config auth.Config) (http.Handler, func(), error) {
	server, err := auth.NewServer(config)
	if err != nil {
		return nil, nil, err
	}
	mux := http.NewServeMux()
	mux.Handle("/auth/", server)
	mux.Handle("/healthz", server)
	mux.HandleFunc("GET /api/profile", func(w http.ResponseWriter, r *http.Request) {
		user, ok := server.CurrentUser(w, r)
		if !ok {
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(w).Encode(map[string]any{"user": user})
	})
	return mux, server.Close, nil
}

func main() {
	config, err := auth.LoadConfig()
	if err != nil {
		log.Fatal(err)
	}
	handler, closeStore, err := newHandler(config)
	if err != nil {
		log.Fatal("could not initialize authentication server")
	}
	defer closeStore()
	config.Password, config.DatabaseURL = "", ""
	server := &http.Server{
		Addr: net.JoinHostPort(config.Host, config.Port), Handler: handler,
		ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second,
		WriteTimeout: 15 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16 * 1024,
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Printf("consumer-go listening on %s", server.Addr)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal("consumer HTTP server failed")
	}
}
