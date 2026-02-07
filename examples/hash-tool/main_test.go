package main

import (
	"testing"
)

func TestComputeHash(t *testing.T) {
	input := "hello world"

	tests := []struct {
		name      string
		algorithm string
		want      string
		wantErr   bool
	}{
		{
			name:      "md5",
			algorithm: "md5",
			want:      "5eb63bbbe01eeed093cb22bb8f5acdc3",
			wantErr:   false,
		},
		{
			name:      "sha256",
			algorithm: "sha256",
			want:      "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
			wantErr:   false,
		},
		{
			name:      "unsupported",
			algorithm: "foo",
			want:      "",
			wantErr:   true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := computeHash(input, tt.algorithm)
			if (err != nil) != tt.wantErr {
				t.Errorf("computeHash() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("computeHash() = %v, want %v", got, tt.want)
			}
		})
	}
}
