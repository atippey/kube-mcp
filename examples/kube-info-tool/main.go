package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

var clientset *kubernetes.Clientset

type NamespaceInfo struct {
	Name   string `json:"name"`
	Status string `json:"status"`
}

type NamespacesResponse struct {
	Namespaces []NamespaceInfo `json:"namespaces,omitempty"`
	Error      string          `json:"error,omitempty"`
}

type PodInfo struct {
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
	Status    string `json:"status"`
	Node      string `json:"node"`
}

type PodsRequest struct {
	Namespace string `json:"namespace"`
}

type PodsResponse struct {
	Pods  []PodInfo `json:"pods,omitempty"`
	Error string    `json:"error,omitempty"`
}

func main() {
	config, err := rest.InClusterConfig()
	if err != nil {
		log.Fatalf("Failed to get in-cluster config: %v", err)
	}

	clientset, err = kubernetes.NewForConfig(config)
	if err != nil {
		log.Fatalf("Failed to create Kubernetes client: %v", err)
	}

	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/namespaces", handleNamespaces)
	http.HandleFunc("/pods", handlePods)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting kube-info-tool server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func handleNamespaces(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	nsList, err := clientset.CoreV1().Namespaces().List(context.Background(), metav1.ListOptions{})
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(NamespacesResponse{Error: err.Error()})
		return
	}

	namespaces := make([]NamespaceInfo, 0, len(nsList.Items))
	for _, ns := range nsList.Items {
		namespaces = append(namespaces, NamespaceInfo{
			Name:   ns.Name,
			Status: string(ns.Status.Phase),
		})
	}

	json.NewEncoder(w).Encode(NamespacesResponse{Namespaces: namespaces})
}

func handlePods(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req PodsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(PodsResponse{Error: "invalid request body"})
		return
	}

	namespace := req.Namespace
	if namespace == "" {
		namespace = "default"
	}

	podList, err := clientset.CoreV1().Pods(namespace).List(context.Background(), metav1.ListOptions{})
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(PodsResponse{Error: err.Error()})
		return
	}

	pods := make([]PodInfo, 0, len(podList.Items))
	for _, pod := range podList.Items {
		pods = append(pods, PodInfo{
			Name:      pod.Name,
			Namespace: pod.Namespace,
			Status:    string(pod.Status.Phase),
			Node:      pod.Spec.NodeName,
		})
	}

	json.NewEncoder(w).Encode(PodsResponse{Pods: pods})
}
