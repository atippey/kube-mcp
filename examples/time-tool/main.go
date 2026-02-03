package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"
)

type TimeRequest struct {
	Timezone string `json:"timezone"`
	Format   string `json:"format"`
}

type TimeResponse struct {
	Time     string `json:"time"`
	Timezone string `json:"timezone"`
	Error    string `json:"error,omitempty"`
}

func main() {
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/time", handleTime)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting time-tool server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func handleTime(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req TimeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(TimeResponse{Error: "invalid request body"})
		return
	}

	targetTimezone := req.Timezone
	if targetTimezone == "" {
		targetTimezone = "UTC"
	}

	loc, err := time.LoadLocation(targetTimezone)
	if err != nil {
		json.NewEncoder(w).Encode(TimeResponse{Error: fmt.Sprintf("invalid timezone: %v", err)})
		return
	}

	now := time.Now().In(loc)
	var formattedTime string

	switch req.Format {
	case "rfc3339", "RFC3339", "":
		formattedTime = now.Format(time.RFC3339)
	case "unix", "Unix":
		formattedTime = fmt.Sprintf("%d", now.Unix())
	case "human", "Human":
		formattedTime = now.Format("2006-01-02 15:04:05 MST")
	default:
		json.NewEncoder(w).Encode(TimeResponse{Error: fmt.Sprintf("unsupported format: %s", req.Format)})
		return
	}

	resp := TimeResponse{
		Time:     formattedTime,
		Timezone: targetTimezone,
	}

	json.NewEncoder(w).Encode(resp)
}
