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
	"strings"
	"syscall"
	"time"

	"github.com/jongko54/feature-standards/implementations/go-net-http/auth"
	"github.com/jongko54/feature-standards/libraries/go/authorization"
	"github.com/jongko54/feature-standards/libraries/go/listing"
)

type membershipProvider func(map[string]string) (*authorization.Principal, error)

func newHandler(config auth.Config, membership membershipProvider) (http.Handler, func(), error) {
	if config.Demo {
		return handlerWithDocuments(config, membership, demoDocuments())
	}
	return handlerWithDocuments(config, membership, currentDocuments())
}

type document struct {
	tenantID, ownerID string
	fields            map[string]any
}

func demoDocuments() []document {
	return []document{
		{"tenant-a", "demo-user", map[string]any{"id": "own-b", "name": "Beta", "score": 2, "active": false}},
		{"tenant-a", "other-user", map[string]any{"id": "other-owner", "name": "Private", "score": 10, "active": true}},
		{"tenant-b", "demo-user", map[string]any{"id": "other-tenant", "name": "Secret", "score": 99, "active": true}},
		{"tenant-a", "demo-user", map[string]any{"id": "own-a", "name": "Alpha", "score": 2, "active": true}},
	}
}

func demoMembership(user map[string]string) (*authorization.Principal, error) {
	if user["id"] != "demo-user" {
		return nil, nil
	}
	return &authorization.Principal{SubjectID: user["id"], TenantID: "tenant-a", Roles: []string{"viewer"}}, nil
}

// Replace with the application's trusted current membership service.
// No configured membership means deny, even when authentication succeeds.
func currentMembership(user map[string]string) (*authorization.Principal, error) {
	return nil, nil
}

// Replace with a server-owned bounded document snapshot. Public demo rows are
// selected only by explicit AUTH_DEMO=true, never by browser headers or queries.
func currentDocuments() []document { return nil }

func productResponse(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func productError(w http.ResponseWriter, status int, code string) {
	productResponse(w, status, map[string]any{"error": map[string]string{"code": code, "message": "Request could not be completed."}})
}

func publicDocument(value document) (map[string]any, bool) {
	public := make(map[string]any, 4)
	for _, key := range []string{"id", "name", "score", "active"} {
		field, found := value.fields[key]
		if !found {
			return nil, false
		}
		public[key] = field
	}
	return public, true
}

func handlerWithDocuments(config auth.Config, membership membershipProvider, documents []document) (http.Handler, func(), error) {
	if membership == nil {
		return nil, nil, errors.New("membership-provider-required")
	}
	policy, err := authorization.NewPolicy([]authorization.Grant{
		{Role: "viewer", Permission: "documents:list", Scope: "tenant"},
		{Role: "viewer", Permission: "documents:read", Scope: "owner"},
	})
	if err != nil {
		return nil, nil, err
	}
	schema, err := listing.NewSchema(
		map[string]string{"id": "string", "name": "string", "score": "integer", "active": "boolean"},
		map[string]string{"name": "string", "score": "integer", "active": "boolean"},
	)
	if err != nil {
		return nil, nil, err
	}
	server, err := auth.NewServer(config)
	if err != nil {
		return nil, nil, err
	}
	// Keep resource attributes and public projection server-owned.
	owned := make([]document, len(documents))
	for index, item := range documents {
		fields := make(map[string]any, len(item.fields))
		for key, value := range item.fields {
			fields[key] = value
		}
		owned[index] = document{item.tenantID, item.ownerID, fields}
	}
	principalFor := func(w http.ResponseWriter, r *http.Request) (*authorization.Principal, bool) {
		user, ok := server.CurrentUser(w, r)
		if !ok {
			return nil, false
		}
		authenticatedSubject := user["id"]
		membershipInput := make(map[string]string, len(user))
		for key, value := range user {
			membershipInput[key] = value
		}
		principal, err := membership(membershipInput)
		if err != nil {
			productError(w, 503, "AUTHORIZATION_UNAVAILABLE")
			return nil, false
		}
		if principal == nil || principal.SubjectID != authenticatedSubject {
			productError(w, 403, "FORBIDDEN")
			return nil, false
		}
		return principal, true
	}
	resource := func(item document) authorization.Resource {
		owner := item.ownerID
		return authorization.Resource{TenantID: item.tenantID, OwnerID: &owner}
	}
	mux := http.NewServeMux()
	mux.Handle("/auth/", server)
	mux.Handle("/healthz", server)
	mux.HandleFunc("GET /api/profile", func(w http.ResponseWriter, r *http.Request) {
		user, ok := server.CurrentUser(w, r)
		if !ok {
			return
		}
		productResponse(w, http.StatusOK, map[string]any{"user": user})
	})
	mux.HandleFunc("GET /api/documents", func(w http.ResponseWriter, r *http.Request) {
		principal, ok := principalFor(w, r)
		if !ok {
			return
		}
		if !policy.Decide(principal, "documents:list", authorization.Resource{TenantID: principal.TenantID}).Allowed {
			productError(w, 403, "FORBIDDEN")
			return
		}
		visible := make([]map[string]any, 0)
		for _, item := range owned {
			if !policy.Decide(principal, "documents:read", resource(item)).Allowed {
				continue
			}
			public, ok := publicDocument(item)
			if !ok {
				productError(w, 500, "INVALID_LIST_DATA")
				return
			}
			visible = append(visible, public)
		}
		query, err := listing.ParseQuery(r.URL.RawQuery, schema)
		if err == nil {
			result, pageError := listing.Page(visible, query, schema)
			if pageError == nil {
				productResponse(w, 200, result)
				return
			}
			err = pageError
		}
		code := "INVALID_LIST_DATA"
		var contractError *listing.Error
		if errors.As(err, &contractError) {
			code = contractError.Code
		}
		status := 500
		if code == "INVALID_LIST_QUERY" {
			status = 400
		}
		productError(w, status, code)
	})
	mux.HandleFunc("GET /api/documents/{documentID}", func(w http.ResponseWriter, r *http.Request) {
		principal, ok := principalFor(w, r)
		if !ok {
			return
		}
		for _, item := range owned {
			if item.fields["id"] != r.PathValue("documentID") {
				continue
			}
			if !policy.Decide(principal, "documents:read", resource(item)).Allowed {
				productError(w, 403, "FORBIDDEN")
				return
			}
			public, ok := publicDocument(item)
			if !ok {
				productError(w, 500, "INVALID_LIST_DATA")
				return
			}
			productResponse(w, 200, public)
			return
		}
		productError(w, 403, "FORBIDDEN")
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") {
			w.Header().Set("Cache-Control", "no-store")
			w.Header().Set("X-Content-Type-Options", "nosniff")
			if r.Method != http.MethodGet {
				w.Header().Set("Allow", "GET")
				productError(w, 405, "METHOD_NOT_ALLOWED")
				return
			}
		}
		mux.ServeHTTP(w, r)
	}), server.Close, nil
}

func main() {
	config, err := auth.LoadConfig()
	if err != nil {
		log.Fatal("invalid authentication configuration")
	}
	if config.Store != "memory" || config.AccountLifecycle {
		log.Fatal("core starter supports browser-session-v1 memory sessions only")
	}
	if config.Demo && config.Host != "localhost" {
		host := net.ParseIP(config.Host)
		if host == nil || !host.IsLoopback() {
			log.Fatal("explicit demo requires a loopback AUTH_HOST")
		}
	}
	membership := currentMembership
	if config.Demo {
		membership = demoMembership
	}
	handler, closeStore, err := newHandler(config, membership)
	if err != nil {
		log.Fatal("could not initialize core consumer")
	}
	defer closeStore()
	config.Password, config.DatabaseURL = "", ""
	server := &http.Server{Addr: net.JoinHostPort(config.Host, config.Port), Handler: handler,
		ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 15 * time.Second,
		IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16 * 1024}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Printf("core starter listening on %s", server.Addr)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal("consumer HTTP server failed")
	}
}
