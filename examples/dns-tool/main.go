package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
)

type LookupRequest struct {
	Hostname string `json:"hostname"`
	Type     string `json:"type"` // A, AAAA, MX, TXT, CNAME
}

type LookupResponse struct {
	Hostname string   `json:"hostname"`
	Type     string   `json:"type"`
	Records  []string `json:"records"`
	TTL      int      `json:"ttl"`
	Error    string   `json:"error,omitempty"`
}

func main() {
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/lookup", handleLookup)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting dns-tool server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func handleLookup(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req LookupRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(LookupResponse{Error: "invalid request body"})
		return
	}

	if req.Hostname == "" {
		json.NewEncoder(w).Encode(LookupResponse{Error: "hostname is required"})
		return
	}
	if req.Type == "" {
		req.Type = "A"
	}

	resp := performLookup(req.Hostname, req.Type)
	json.NewEncoder(w).Encode(resp)
}

func performLookup(hostname, recordType string) LookupResponse {
	resp := LookupResponse{
		Hostname: hostname,
		Type:     recordType,
		TTL:      300, // Dummy TTL as net package doesn't provide it
	}

	var err error
	switch recordType {
	case "A":
		var ips []net.IP
		ips, err = net.LookupIP(hostname)
		if err == nil {
			for _, ip := range ips {
				if ip.To4() != nil {
					resp.Records = append(resp.Records, ip.String())
				}
			}
		}
	case "AAAA":
		var ips []net.IP
		ips, err = net.LookupIP(hostname)
		if err == nil {
			for _, ip := range ips {
				if ip.To4() == nil {
					resp.Records = append(resp.Records, ip.String())
				}
			}
		}
	case "MX":
		var mxs []*net.MX
		mxs, err = net.LookupMX(hostname)
		if err == nil {
			for _, mx := range mxs {
				resp.Records = append(resp.Records, fmt.Sprintf("%d %s", mx.Pref, mx.Host))
			}
		}
	case "TXT":
		var txts []string
		txts, err = net.LookupTXT(hostname)
		if err == nil {
			resp.Records = txts
		}
	case "CNAME":
		var cname string
		cname, err = net.LookupCNAME(hostname)
		if err == nil {
			resp.Records = append(resp.Records, cname)
		}
	default:
		resp.Error = fmt.Sprintf("unsupported record type: %s", recordType)
		return resp
	}

	if err != nil {
		resp.Error = err.Error()
	}

	// Ensure records is not nil for JSON output
	if resp.Records == nil {
		resp.Records = []string{}
	}

	return resp
}
