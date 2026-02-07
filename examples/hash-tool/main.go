package main

import (
	"crypto/md5"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
)

// HashRequest represents the incoming request body
type HashRequest struct {
	Input     string `json:"input"`
	Algorithm string `json:"algorithm"` // md5, sha1, sha256, sha512
}

// HashResponse represents the outgoing response body
type HashResponse struct {
	Hash        string `json:"hash"`
	Algorithm   string `json:"algorithm"`
	InputLength int    `json:"input_length"`
	Error       string `json:"error,omitempty"`
}

func main() {
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/hash", handleHash)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting hash-tool server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func handleHash(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req HashRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(HashResponse{Error: "invalid request body"})
		return
	}

	if req.Input == "" {
		json.NewEncoder(w).Encode(HashResponse{Error: "input is required"})
		return
	}

	if req.Algorithm == "" {
		json.NewEncoder(w).Encode(HashResponse{Error: "algorithm is required"})
		return
	}

	hash, err := computeHash(req.Input, req.Algorithm)
	if err != nil {
		json.NewEncoder(w).Encode(HashResponse{Error: err.Error()})
		return
	}

	resp := HashResponse{
		Hash:        hash,
		Algorithm:   req.Algorithm,
		InputLength: len(req.Input),
	}

	json.NewEncoder(w).Encode(resp)
}

func computeHash(input, algorithm string) (string, error) {
	data := []byte(input)
	switch algorithm {
	case "md5":
		sum := md5.Sum(data)
		return hex.EncodeToString(sum[:]), nil
	case "sha1":
		sum := sha1.Sum(data)
		return hex.EncodeToString(sum[:]), nil
	case "sha256":
		sum := sha256.Sum256(data)
		return hex.EncodeToString(sum[:]), nil
	case "sha512":
		sum := sha512.Sum512(data)
		return hex.EncodeToString(sum[:]), nil
	default:
		return "", fmt.Errorf("unsupported algorithm: %s", algorithm)
	}
}
