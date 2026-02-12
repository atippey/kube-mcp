package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"os"
	"strings"
)

type WeatherRequest struct {
	City string `json:"city"`
}

type WeatherResponse struct {
	Temperature int    `json:"temperature"`
	Conditions  string `json:"conditions"`
	Humidity    int    `json:"humidity"`
	Error       string `json:"error,omitempty"`
}

func main() {
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/weather", handleWeather)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting weather-tool server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func handleWeather(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req WeatherRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(WeatherResponse{Error: "invalid JSON body"})
		return
	}

	if strings.TrimSpace(req.City) == "" {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(WeatherResponse{Error: "city is required"})
		return
	}

	// Mock logic
	temp := 40 + rand.Intn(61) // 40 to 100
	conditions := []string{"sunny", "cloudy", "rainy", "snowy"}
	condition := conditions[rand.Intn(len(conditions))]
	humidity := rand.Intn(101) // 0 to 100

	resp := WeatherResponse{
		Temperature: temp,
		Conditions:  condition,
		Humidity:    humidity,
	}

	fmt.Printf("Weather request for %s: %d°F, %s, %d%%\n", req.City, temp, condition, humidity)

	json.NewEncoder(w).Encode(resp)
}
