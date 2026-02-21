package main

import (
	"fmt"
	"reflect"

	"github.com/google/cel-go/cel"
)

type CELRule struct {
	ID          string
	Severity    string
	Category    string
	Expr        string
	Message     string
	Remediation string
	Evidence    string
	Package     string
}

func evaluateCELRules(ctx map[string]any, rules []CELRule) []Finding {
	findings := []Finding{}
	if len(rules) == 0 {
		return findings
	}

	env, err := cel.NewEnv(buildCELDecls(ctx)...)
	if err != nil {
		return []Finding{{
			ID:       "RULE-ENGINE-001",
			Severity: "HIGH",
			Category: "engine",
			Message:  fmt.Sprintf("CEL environment creation failed: %v", err),
		}}
	}

	for _, rule := range rules {
		ast, iss := env.Compile(rule.Expr)
		if iss != nil && iss.Err() != nil {
			findings = append(findings, Finding{
				ID:       "RULE-ENGINE-002",
				Severity: "HIGH",
				Category: "engine",
				Message:  fmt.Sprintf("CEL compile failed for %s: %v", rule.ID, iss.Err()),
			})
			continue
		}

		prg, err := env.Program(ast)
		if err != nil {
			findings = append(findings, Finding{
				ID:       "RULE-ENGINE-003",
				Severity: "HIGH",
				Category: "engine",
				Message:  fmt.Sprintf("CEL program build failed for %s: %v", rule.ID, err),
			})
			continue
		}

		out, _, err := prg.Eval(ctx)
		if err != nil {
			findings = append(findings, Finding{
				ID:       "RULE-ENGINE-004",
				Severity: "HIGH",
				Category: "engine",
				Message:  fmt.Sprintf("CEL eval failed for %s: %v", rule.ID, err),
			})
			continue
		}

		val, ok := out.Value().(bool)
		if !ok || !val {
			continue
		}
		findings = append(findings, Finding{
			ID:          rule.ID,
			Severity:    rule.Severity,
			Category:    rule.Category,
			Package:     rule.Package,
			Message:     rule.Message,
			Remediation: rule.Remediation,
			Evidence:    rule.Evidence,
		})
	}

	return findings
}

func buildCELDecls(ctx map[string]any) []cel.EnvOption {
	decls := []cel.EnvOption{}
	for k, v := range ctx {
		switch reflect.TypeOf(v).Kind() {
		case reflect.Bool:
			decls = append(decls, cel.Variable(k, cel.BoolType))
		case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
			decls = append(decls, cel.Variable(k, cel.IntType))
		case reflect.Float32, reflect.Float64:
			decls = append(decls, cel.Variable(k, cel.DoubleType))
		default:
			decls = append(decls, cel.Variable(k, cel.StringType))
		}
	}
	return decls
}
