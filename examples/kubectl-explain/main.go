package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"slices"
	"strings"

	"k8s.io/client-go/discovery"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/kube-openapi/pkg/util/proto"
)

// ExplainRequest represents the incoming request body
type ExplainRequest struct {
	Resource  string `json:"resource"`  // e.g., "pod", "deployment.spec.replicas"
	Recursive bool   `json:"recursive"` // if true, expand nested fields
	MaxDepth  int    `json:"maxDepth"`  // limit recursion depth (default 5)
}

// ExplainResponse represents the response
type ExplainResponse struct {
	Resource    string   `json:"resource"`
	Kind        string   `json:"kind,omitempty"`
	Description string   `json:"description,omitempty"`
	Type        string   `json:"type,omitempty"`
	Fields      []Field  `json:"fields,omitempty"`
	Error       string   `json:"error,omitempty"`
}

// Field represents a field in the schema
type Field struct {
	Name        string  `json:"name"`
	Type        string  `json:"type"`
	Description string  `json:"description,omitempty"`
	Required    bool    `json:"required,omitempty"`
	Fields      []Field `json:"fields,omitempty"` // nested fields when recursive
}

var discoveryClient *discovery.DiscoveryClient

func main() {
	// Initialize Kubernetes client
	if err := initKubeClient(); err != nil {
		log.Fatalf("Failed to initialize Kubernetes client: %v", err)
	}

	// HTTP routes
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/explain", handleExplain)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting kubectl-explain server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func initKubeClient() error {
	var config *rest.Config
	var err error

	// Try in-cluster config first
	config, err = rest.InClusterConfig()
	if err != nil {
		// Fall back to kubeconfig
		kubeconfig := os.Getenv("KUBECONFIG")
		if kubeconfig == "" {
			kubeconfig = os.Getenv("HOME") + "/.kube/config"
		}
		config, err = clientcmd.BuildConfigFromFlags("", kubeconfig)
		if err != nil {
			return fmt.Errorf("failed to build config: %w", err)
		}
	}

	discoveryClient, err = discovery.NewDiscoveryClientForConfig(config)
	if err != nil {
		return fmt.Errorf("failed to create discovery client: %w", err)
	}

	return nil
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func handleExplain(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req ExplainRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(ExplainResponse{Error: "invalid request body"})
		return
	}

	if req.Resource == "" {
		json.NewEncoder(w).Encode(ExplainResponse{Error: "resource is required"})
		return
	}

	// Default max depth
	maxDepth := req.MaxDepth
	if maxDepth <= 0 {
		maxDepth = 5
	}

	response := explainResource(req.Resource, req.Recursive, maxDepth)
	json.NewEncoder(w).Encode(response)
}

func explainResource(resource string, recursive bool, maxDepth int) ExplainResponse {
	// Parse resource path (e.g., "pod.spec.containers" -> kind="pod", path=["spec", "containers"])
	parts := strings.Split(strings.ToLower(resource), ".")
	kind := parts[0]
	fieldPath := parts[1:]

	// Fetch OpenAPI schema
	doc, err := discoveryClient.OpenAPISchema()
	if err != nil {
		return ExplainResponse{Resource: resource, Error: fmt.Sprintf("failed to fetch OpenAPI schema: %v", err)}
	}

	// Parse the OpenAPI document
	models, err := proto.NewOpenAPIData(doc)
	if err != nil {
		return ExplainResponse{Resource: resource, Error: fmt.Sprintf("failed to parse OpenAPI schema: %v", err)}
	}

	// Find the schema for the requested kind
	schema := findSchemaForKind(models, kind)
	if schema == nil {
		return ExplainResponse{Resource: resource, Error: fmt.Sprintf("unknown resource: %s", kind)}
	}

	// Navigate to the requested field path
	currentSchema := schema
	for _, field := range fieldPath {
		currentSchema = navigateToField(currentSchema, field)
		if currentSchema == nil {
			return ExplainResponse{Resource: resource, Error: fmt.Sprintf("unknown field: %s", strings.Join(fieldPath, "."))}
		}
	}

	// Build response from schema
	return buildResponse(resource, currentSchema, models, recursive, maxDepth)
}

func findSchemaForKind(models proto.Models, kind string) proto.Schema {
	// Common API group mappings
	kindMappings := map[string][]string{
		"pod":         {"io.k8s.api.core.v1.Pod"},
		"deployment":  {"io.k8s.api.apps.v1.Deployment"},
		"service":     {"io.k8s.api.core.v1.Service"},
		"configmap":   {"io.k8s.api.core.v1.ConfigMap"},
		"secret":      {"io.k8s.api.core.v1.Secret"},
		"namespace":   {"io.k8s.api.core.v1.Namespace"},
		"node":        {"io.k8s.api.core.v1.Node"},
		"ingress":     {"io.k8s.api.networking.v1.Ingress"},
		"statefulset": {"io.k8s.api.apps.v1.StatefulSet"},
		"daemonset":   {"io.k8s.api.apps.v1.DaemonSet"},
		"job":         {"io.k8s.api.batch.v1.Job"},
		"cronjob":     {"io.k8s.api.batch.v1.CronJob"},
	}

	if refs, ok := kindMappings[kind]; ok {
		for _, ref := range refs {
			if schema := models.LookupModel(ref); schema != nil {
				return schema
			}
		}
	}

	// Try to find by iterating all models (fallback)
	// This is expensive but handles CRDs and unknown types
	return nil
}

func navigateToField(schema proto.Schema, fieldName string) proto.Schema {
	if schema == nil {
		return nil
	}

	// Handle Kind (object with fields)
	if kind, ok := schema.(*proto.Kind); ok {
		for _, key := range kind.Keys() {
			if strings.EqualFold(key, fieldName) {
				return kind.Fields[key]
			}
		}
	}

	// Handle Map
	if m, ok := schema.(*proto.Map); ok {
		return m.SubType
	}

	// Handle Array
	if arr, ok := schema.(*proto.Array); ok {
		// If accessing array, navigate into element type
		return navigateToField(arr.SubType, fieldName)
	}

	return nil
}

// resolveSchema follows proto.Ref to get the actual schema
func resolveSchema(schema proto.Schema, models proto.Models) proto.Schema {
	if ref, ok := schema.(*proto.Ref); ok {
		if resolved := models.LookupModel(ref.Reference()); resolved != nil {
			return resolved
		}
	}
	return schema
}

func buildResponse(resource string, schema proto.Schema, models proto.Models, recursive bool, maxDepth int) ExplainResponse {
	// Resolve references first
	schema = resolveSchema(schema, models)

	resp := ExplainResponse{
		Resource:    resource,
		Description: schema.GetDescription(),
	}

	switch s := schema.(type) {
	case *proto.Kind:
		resp.Kind = "object"
		resp.Type = "object"
		resp.Fields = buildFields(s, models, recursive, maxDepth, 0)

	case *proto.Primitive:
		resp.Type = s.Type

	case *proto.Array:
		resp.Type = "[]" + getTypeName(s.SubType)

	case *proto.Map:
		resp.Type = "map[string]" + getTypeName(s.SubType)

	case *proto.Ref:
		resp.Type = s.Reference()
	}

	return resp
}

func buildFields(kind *proto.Kind, models proto.Models, recursive bool, maxDepth, currentDepth int) []Field {
	var fields []Field

	for _, key := range kind.Keys() {
		fieldSchema := kind.Fields[key]
		f := Field{
			Name:        key,
			Description: fieldSchema.GetDescription(),
			Required:    slices.Contains(kind.RequiredFields, key),
		}

		// Resolve references
		resolved := resolveSchema(fieldSchema, models)

		// Determine type and recurse if needed
		switch ft := resolved.(type) {
		case *proto.Primitive:
			f.Type = ft.Type
		case *proto.Kind:
			f.Type = "object"
			if recursive && currentDepth < maxDepth {
				f.Fields = buildFields(ft, models, recursive, maxDepth, currentDepth+1)
			}
		case *proto.Array:
			f.Type = "[]" + getTypeName(ft.SubType)
			// Recurse into array element type if it's an object
			if recursive && currentDepth < maxDepth {
				subResolved := resolveSchema(ft.SubType, models)
				if subKind, ok := subResolved.(*proto.Kind); ok {
					f.Fields = buildFields(subKind, models, recursive, maxDepth, currentDepth+1)
				}
			}
		case *proto.Map:
			f.Type = "map[string]" + getTypeName(ft.SubType)
		case *proto.Ref:
			// Unresolved ref - just show the type
			f.Type = ft.Reference()
		default:
			f.Type = "unknown"
		}

		fields = append(fields, f)
	}

	return fields
}

func getTypeName(schema proto.Schema) string {
	switch s := schema.(type) {
	case *proto.Primitive:
		return s.Type
	case *proto.Kind:
		return "object"
	case *proto.Ref:
		return s.Reference()
	default:
		return "unknown"
	}
}

