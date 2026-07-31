import { useState, type FormEvent } from "react";
import styles from "./profileForm.module.css";
import {
  PREFERRED_COUNTRY_ANY,
  ACADEMIC_BACKGROUND_OPTIONS,
  MIGRATION_INTENT_OPTIONS,
  type AcademicBackground,
  type MigrationIntent,
  type ProfileFormValues,
} from "./types";

export interface ProfileFormProps {
  onSubmit: (values: ProfileFormValues) => void;
  isSubmitting: boolean;
  disabled?: boolean;
  /** Countries to offer, in addition to "Any / Let AI decide". Defaults to the 16 countries actually in AIEC's course database. */
  countries?: string[];
}

const DEFAULT_COUNTRIES = [
  "Australia",
  "USA",
  "Canada",
  "New Zealand",
  "UK",
  "Japan",
  "South Korea",
  "Malta",
  "Germany",
  "Netherlands",
  "Finland",
  "Cyprus",
  "Romania",
  "Ireland",
  "Dubai (UAE)",
  "Denmark",
];

export function ProfileForm({ onSubmit, isSubmitting, disabled, countries = DEFAULT_COUNTRIES }: ProfileFormProps) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [gpa, setGpa] = useState("");
  const [ielts, setIelts] = useState("");
  const [budget, setBudget] = useState("");
  const [gap, setGap] = useState("0");
  const [academicBackground, setAcademicBackground] = useState<AcademicBackground>("bachelors");
  const [careerGoals, setCareerGoals] = useState("");
  const [migrationIntent, setMigrationIntent] = useState<MigrationIntent>("undecided");
  const [preferredCountry, setPreferredCountry] = useState(PREFERRED_COUNTRY_ANY);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({
      fullName,
      email,
      phone,
      gpa: Number(gpa),
      ielts: Number(ielts),
      budget: Number(budget),
      gap: Number(gap),
      academicBackground,
      careerGoals,
      migrationIntent,
      preferredCountry,
    });
  };

  const isValid =
    fullName.trim().length > 0 &&
    email.trim().length > 0 &&
    phone.trim().length > 0 &&
    gpa.trim().length > 0 &&
    ielts.trim().length > 0 &&
    budget.trim().length > 0;

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.header}>
        <h3 className={styles.title}>Student Profile</h3>
        <p className={styles.subtitle}>All fields are required for accurate analysis</p>
      </div>

      <label className={styles.field}>
        <span className={styles.label}>Full Name</span>
        <input
          className={styles.input}
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          placeholder="e.g. Priya Sharma"
          disabled={disabled}
        />
      </label>

      <div className={styles.row}>
        <label className={styles.field}>
          <span className={styles.label}>Email Address</span>
          <input
            className={styles.input}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="e.g. priya@gmail.com"
            disabled={disabled}
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Phone Number</span>
          <input
            className={styles.input}
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="e.g. +977 98XXXXXXXX"
            disabled={disabled}
          />
        </label>
      </div>

      <div className={styles.row}>
        <label className={styles.field}>
          <span className={styles.label}>
            GPA <span className={styles.hint}>(out of 4.0)</span>
          </span>
          <input
            className={styles.input}
            type="number"
            step="0.01"
            min="0"
            max="4"
            value={gpa}
            onChange={(e) => setGpa(e.target.value)}
            placeholder="e.g. 3.2"
            disabled={disabled}
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>
            IELTS Score <span className={styles.hint}>(0–9)</span>
          </span>
          <input
            className={styles.input}
            type="number"
            step="0.5"
            min="0"
            max="9"
            value={ielts}
            onChange={(e) => setIelts(e.target.value)}
            placeholder="e.g. 6.5"
            disabled={disabled}
          />
        </label>
      </div>

      <div className={styles.row}>
        <label className={styles.field}>
          <span className={styles.label}>
            Annual Budget (USD) <span className={styles.hint}>— tuition + living</span>
          </span>
          <input
            className={styles.input}
            type="number"
            min="0"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="e.g. 20000"
            disabled={disabled}
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>
            Study Gap <span className={styles.hint}>(years since last education)</span>
          </span>
          <input
            className={styles.input}
            type="number"
            min="0"
            max="50"
            step="1"
            value={gap}
            onChange={(e) => setGap(e.target.value)}
            placeholder="e.g. 1"
            disabled={disabled}
          />
        </label>
      </div>

      <div className={styles.row}>
        <label className={styles.field}>
          <span className={styles.label}>Academic Background</span>
          <select
            className={styles.select}
            value={academicBackground}
            onChange={(e) => setAcademicBackground(e.target.value as AcademicBackground)}
            disabled={disabled}
          >
            {ACADEMIC_BACKGROUND_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Migration Intent</span>
          <select
            className={styles.select}
            value={migrationIntent}
            onChange={(e) => setMigrationIntent(e.target.value as MigrationIntent)}
            disabled={disabled}
          >
            {MIGRATION_INTENT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className={styles.field}>
        <span className={styles.label}>
          Career Goals <span className={styles.hint}>(optional)</span>
        </span>
        <input
          className={styles.input}
          value={careerGoals}
          onChange={(e) => setCareerGoals(e.target.value)}
          placeholder="e.g. Become a data analyst in the tech industry"
          disabled={disabled}
        />
      </label>

      <label className={styles.field}>
        <span className={styles.label}>Preferred Country</span>
        <select
          className={styles.select}
          value={preferredCountry}
          onChange={(e) => setPreferredCountry(e.target.value)}
          disabled={disabled}
        >
          <option value={PREFERRED_COUNTRY_ANY}>Any / Let AI decide</option>
          {countries.map((country) => (
            <option key={country} value={country}>
              {country}
            </option>
          ))}
        </select>
      </label>

      <button className={styles.submitButton} type="submit" disabled={!isValid || isSubmitting || disabled}>
        {isSubmitting ? "Analysing..." : "🤖 Analyse My Profile"}
      </button>
    </form>
  );
}
