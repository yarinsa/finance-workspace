import Form from "@rjsf/core";
import type { RJSFSchema, UiSchema } from "@rjsf/utils";
import validator from "@rjsf/validator-ajv8";

/**
 * A source's connection form, drawn from the JSON Schema it declares in its manifest.
 * Read-only: values live in the Mac's `.env` and never travel through the app, so the form
 * shows what the source needs and the variable each field maps to (`x-env`).
 */
export function connectionUiSchema(schema: RJSFSchema): UiSchema {
  const ui: UiSchema = {
    "ui:readonly": true,
    "ui:submitButtonOptions": { norender: true },
  };
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    const field = prop as RJSFSchema & {
      writeOnly?: boolean;
      "x-env"?: string;
    };
    ui[key] = {
      ...(field.writeOnly ? { "ui:widget": "password" } : {}),
      "ui:help": field["x-env"] ? `ב-.env: ${field["x-env"]}` : undefined,
    };
  }
  return ui;
}

export default function ConnectionForm({ schema }: { schema: RJSFSchema }) {
  return (
    <Form
      className="connection-form"
      schema={schema}
      uiSchema={connectionUiSchema(schema)}
      validator={validator}
      tagName="div"
    />
  );
}
