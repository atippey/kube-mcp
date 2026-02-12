package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"

	"github.com/google/go-containerregistry/pkg/crane"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

var clientset *kubernetes.Clientset

// --- /images types ---

type ImagesRequest struct {
	Namespace string `json:"namespace"`
	Format    string `json:"format"` // "unique" or "pods"
}

type ImageInfo struct {
	Image     string   `json:"image"`
	Pods      []string `json:"pods"`
	Namespace string   `json:"namespace"`
	Container string   `json:"container"`
}

type ImagesResponse struct {
	Images []ImageInfo `json:"images"`
	Count  int         `json:"count"`
	Error  string      `json:"error,omitempty"`
}

// --- /inspect types ---

type InspectRequest struct {
	Image string `json:"image"`
}

type LayerInfo struct {
	Digest    string `json:"digest"`
	Size      int64  `json:"size"`
	MediaType string `json:"mediaType"`
}

type PlatformInfo struct {
	OS           string `json:"os"`
	Architecture string `json:"architecture"`
}

type ConfigInfo struct {
	Env        []string          `json:"env"`
	Entrypoint []string          `json:"entrypoint"`
	Cmd        []string          `json:"cmd"`
	Labels     map[string]string `json:"labels"`
	User       string            `json:"user"`
	WorkingDir string            `json:"workingDir"`
}

type InspectResponse struct {
	Image     string       `json:"image"`
	Digest    string       `json:"digest"`
	MediaType string       `json:"mediaType"`
	Platform  PlatformInfo `json:"platform"`
	Config    ConfigInfo   `json:"config"`
	Layers    []LayerInfo  `json:"layers"`
	TotalSize int64        `json:"totalSize"`
	Created   string       `json:"created"`
	Error     string       `json:"error,omitempty"`
}

func main() {
	// Initialize Kubernetes client
	config, err := rest.InClusterConfig()
	if err != nil {
		kubeconfig := os.Getenv("KUBECONFIG")
		if kubeconfig == "" {
			home, _ := os.UserHomeDir()
			kubeconfig = home + "/.kube/config"
		}
		config, err = clientcmd.BuildConfigFromFlags("", kubeconfig)
		if err != nil {
			log.Printf("Warning: could not load kubeconfig: %v (cluster /images endpoint will not work)", err)
		}
	}

	if config != nil {
		clientset, err = kubernetes.NewForConfig(config)
		if err != nil {
			log.Printf("Warning: could not create kubernetes client: %v", err)
		}
	}

	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/images", handleImages)
	http.HandleFunc("/inspect", handleInspect)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting crane-tool server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func handleImages(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	if clientset == nil {
		json.NewEncoder(w).Encode(ImagesResponse{Error: "kubernetes client not available"})
		return
	}

	var req ImagesRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(ImagesResponse{Error: "invalid request body"})
		return
	}

	namespace := req.Namespace
	if namespace == "" {
		namespace = ""
	}

	pods, err := clientset.CoreV1().Pods(namespace).List(context.Background(), metav1.ListOptions{})
	if err != nil {
		json.NewEncoder(w).Encode(ImagesResponse{Error: fmt.Sprintf("failed to list pods: %v", err)})
		return
	}

	if req.Format == "pods" {
		// Per-pod format: one entry per container per pod
		var images []ImageInfo
		for _, pod := range pods.Items {
			for _, container := range pod.Spec.Containers {
				images = append(images, ImageInfo{
					Image:     container.Image,
					Pods:      []string{pod.Name},
					Namespace: pod.Namespace,
					Container: container.Name,
				})
			}
		}
		if images == nil {
			images = []ImageInfo{}
		}
		json.NewEncoder(w).Encode(ImagesResponse{Images: images, Count: len(images)})
		return
	}

	// Default: unique format - deduplicate by image reference
	imageMap := make(map[string]*ImageInfo)
	for _, pod := range pods.Items {
		for _, container := range pod.Spec.Containers {
			key := container.Image
			if existing, ok := imageMap[key]; ok {
				// Add pod name if not already present
				found := false
				for _, p := range existing.Pods {
					if p == pod.Name {
						found = true
						break
					}
				}
				if !found {
					existing.Pods = append(existing.Pods, pod.Name)
				}
			} else {
				imageMap[key] = &ImageInfo{
					Image:     container.Image,
					Pods:      []string{pod.Name},
					Namespace: pod.Namespace,
					Container: container.Name,
				}
			}
		}
	}

	var images []ImageInfo
	for _, info := range imageMap {
		images = append(images, *info)
	}
	if images == nil {
		images = []ImageInfo{}
	}

	json.NewEncoder(w).Encode(ImagesResponse{Images: images, Count: len(images)})
}

func handleInspect(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req InspectRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(InspectResponse{Error: "invalid request body"})
		return
	}

	if req.Image == "" {
		json.NewEncoder(w).Encode(InspectResponse{Error: "image is required"})
		return
	}

	// Get the image descriptor
	desc, err := crane.Get(req.Image)
	if err != nil {
		json.NewEncoder(w).Encode(InspectResponse{
			Image: req.Image,
			Error: fmt.Sprintf("failed to fetch image: %v", err),
		})
		return
	}

	resp := InspectResponse{
		Image:     req.Image,
		Digest:    desc.Digest.String(),
		MediaType: string(desc.MediaType),
	}

	// Try to get the image as a v1.Image for detailed info
	img, err := desc.Image()
	if err != nil {
		// Might be an index, return what we have
		json.NewEncoder(w).Encode(resp)
		return
	}

	// Get manifest
	manifest, err := img.Manifest()
	if err == nil {
		resp.MediaType = string(manifest.MediaType)
	}

	// Get config
	configFile, err := img.ConfigFile()
	if err == nil && configFile != nil {
		resp.Created = configFile.Created.Time.Format("2006-01-02T15:04:05Z")
		resp.Platform = PlatformInfo{
			OS:           configFile.OS,
			Architecture: configFile.Architecture,
		}
		resp.Config = ConfigInfo{
			Env:        configFile.Config.Env,
			Entrypoint: configFile.Config.Entrypoint,
			Cmd:        configFile.Config.Cmd,
			Labels:     configFile.Config.Labels,
			User:       configFile.Config.User,
			WorkingDir: configFile.Config.WorkingDir,
		}
		// Ensure non-nil slices for clean JSON
		if resp.Config.Env == nil {
			resp.Config.Env = []string{}
		}
		if resp.Config.Entrypoint == nil {
			resp.Config.Entrypoint = []string{}
		}
		if resp.Config.Cmd == nil {
			resp.Config.Cmd = []string{}
		}
		if resp.Config.Labels == nil {
			resp.Config.Labels = map[string]string{}
		}
	}

	// Get layers
	layers, err := img.Layers()
	if err == nil {
		var totalSize int64
		var layerInfos []LayerInfo
		for _, layer := range layers {
			digest, _ := layer.Digest()
			size, _ := layer.Size()
			mt, _ := layer.MediaType()
			totalSize += size
			layerInfos = append(layerInfos, LayerInfo{
				Digest:    digest.String(),
				Size:      size,
				MediaType: string(mt),
			})
		}
		resp.Layers = layerInfos
		resp.TotalSize = totalSize
	}
	if resp.Layers == nil {
		resp.Layers = []LayerInfo{}
	}

	// Clean up digest display - remove duplicate prefix if present
	if strings.HasPrefix(resp.Digest, "sha256:sha256:") {
		resp.Digest = strings.TrimPrefix(resp.Digest, "sha256:")
	}

	json.NewEncoder(w).Encode(resp)
}
