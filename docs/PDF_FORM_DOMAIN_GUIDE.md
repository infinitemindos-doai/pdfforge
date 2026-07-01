# PDF Form Domain Guide

> **Source:** Anthony's contact (PDF form domain expert), 2026-07-01
> **Purpose:** Comprehensive reference for PDFForge field detection, generation, and QA

---

## 1. Field Properties We Don't Yet Support

### Barcode Fields
- **Types:** PDF417, QR codes, and other barcode formats
- **Properties:**
  - X Dimension (cell width in mils) — controls barcode density
  - Y/X ratio (height-to-width) — controls barcode proportions
  - Error correction level — higher = more reliable reads but larger, more data-limited
  - (applies to PDF417 and QR specifically)
- **Size guidance:** Depends on data volume and scanner distance
  - Small QR for near-field scanning: ~0.5-1 inch
  - Larger for varied lighting/distance conditions

### Signature Fields
- Digital signature placement areas
- Can be certified or standard signatures
- Important for legal/contract form types

### Image Fields
- Collect image uploads (photos, logos, signatures)
- Used in Acrobat Sign workflows for participant-uploaded images

### File Attachment Fields
- Allow file uploads mid-signature workflow
- Acrobat Sign specific field type

### Dropdown / Combo Box Fields
- Select one from a list of options
- Can be editable (user can type custom value) or read-only

---

## 2. Capabilities We're Missing (High Priority)

### JavaScript Scripting
- Custom validation scripts per field (beyond preset Number/Currency)
- Custom formatting scripts
- Custom calculation scripts
- **Implementation:** PyMuPDF supports `script` properties on widgets — we need to expose this

### Field Calculation Order
- For forms with math (totals, sums, tax calculations)
- Controls the sequence fields calculate in
- Critical for financial forms (invoices, expense reports, loan applications)
- **Implementation:** AcroForm `/A` array defines calculation order

### Validation Rules
- Restrict text/dropdown fields to numeric ranges
- Run custom validation scripts
- Built-in types: Number, Currency, Date, Time, Zip, SSN, Phone
- **Implementation:** PyMuPDF widget `field_value` + `script` properties

### Read-Only / Visibility States
A field can be:
1. **Visible** — shown on screen and print
2. **Hidden** — not shown anywhere
3. **Visible-but-non-printing** — shown on screen, not on print
4. **Hidden-but-printable** — not on screen, appears on print
- **Implementation:** AcroForm field flags `PDF_WIDGET_F_HIDDEN`, `PDF_WIDGET_F_NO_VIEW`, `PDF_WIDGET_F_NO_PRINT`

### Data Export/Import
- Encode form data as XFDF or XML
- For merging with external systems
- **Implementation:** PyMuPDF `doc.xref_xml_metadata()` and XFDF export

### Use Current Properties as New Defaults
- Set preferred appearance/size once, apply to all future fields of that type
- **Implementation:** Store a template config in the generator, apply to all fields of matching type

### Accessibility Tagging (Critical)
- **Known Acrobat bug:** Adding form fields doesn't automatically create associated tags
- Forms can be fillable but **invisible to screen readers** unless manually tagged
- Must verify tab order matches visual/reading order
- **Implementation:** 
  - Add `/StructTreeRoot` with marked content sequences
  - Tag each form field with `/Form` role
  - Set `/TU` (tooltip) for screen reader description
  - Verify tab order array matches reading order

---

## 3. Participant Roles (Acrobat Sign Workflows)

For e-signature workflows (not static fillable PDFs):
- Fields can be **assigned to specific signers**
- Extra field types available:
  - Image fields (collect uploads mid-signature)
  - File Attachment fields
- Role-based field assignment: Signer 1, Signer 2, etc.

---

## 4. PDF Form Type Taxonomy (Training Data Targets)

These form types serve as structural templates for CV training data acquisition.
Each category represents distinct structural patterns the CV model must learn.

### Business / Administrative
- Job application form
- New hire onboarding packet
- Employee timesheet
- Expense reimbursement form
- Purchase order form
- Invoice / billing form
- Vendor/supplier registration form
- Non-disclosure agreement (NDA)
- Independent contractor agreement
- W-9 / tax intake form
- Direct deposit authorization
- Performance review form
- Exit interview form

### Legal / Contracts
- Service agreement
- Lease/rental agreement
- Power of attorney
- Liability waiver / release form
- Non-compete agreement
- Licensing agreement
- Settlement agreement
- Consent form

### Healthcare / Intake
- New patient intake form
- Medical history questionnaire
- HIPAA consent/authorization
- Informed consent form
- Insurance claim form
- Prescription request form
- Telehealth consent form

### Financial / Investment
- Loan application
- Investment subscription agreement
- Accredited investor questionnaire
- Client onboarding / KYC form
- Risk tolerance assessment
- Account opening form
- Wire transfer authorization

### Real Estate
- Rental application
- Property inspection checklist
- Purchase offer form
- Lease renewal form
- Maintenance request form
- Move-in/move-out checklist

### Education / Training
- Enrollment/registration form
- Course evaluation form
- Scholarship application
- Field trip permission slip
- Certificate/completion form

### Events
- Event registration form
- RSVP form
- Vendor application (for markets/conferences)
- Sponsorship agreement
- Volunteer sign-up form

### Surveys / Feedback
- Customer satisfaction survey
- Product feedback form
- Market research questionnaire
- Employee engagement survey

### Membership / Subscription
- Membership application
- Subscription order form
- Renewal form
- Cancellation request form

### Government / Compliance
- Permit application
- Tax filing form
- FOIA request form
- Grant application
- Compliance checklist/audit form

### Creative / Content (FLUX Prime relevant)
- Content release / model release form
- Collaboration/partnership agreement
- Sponsorship deliverables form
- Talent/contributor intake form
- Subscriber onboarding form

---

## 5. Implementation Priority

| Feature | Priority | Effort | Phase |
|---------|----------|--------|-------|
| Dropdown fields | High | Low | Next |
| Signature fields | High | Medium | Next |
| Validation rules (Number, Date, Currency) | High | Medium | Next |
| Field calculation order | Medium | Medium | Phase 3 |
| JavaScript scripting support | Medium | High | Phase 3 |
| Read-only / visibility states | High | Low | Next |
| Accessibility tagging | Critical | High | Phase 3 |
| Data export (XFDF/XML) | Low | Medium | Phase 4 |
| Barcode fields | Low | High | Phase 4 |
| Image / File Attachment fields | Low | High | Phase 4 (Acrobat Sign) |
| Participant roles | Low | High | Phase 4 (Acrobat Sign) |
| "Use as default" property templates | Low | Low | Phase 3 |

---

## 6. Training Data Acquisition Strategy

Based on the form type taxonomy above, here are public sources for each category:

| Category | Source | Count Available |
|----------|--------|----------------|
| Government/Tax | IRS.gov forms, state tax sites | 500+ |
| Business | SHRM templates, state labor sites | 200+ |
| Healthcare | CMS.gov, state health depts | 150+ |
| Financial | SEC forms, SBA loan forms | 100+ |
| Real Estate | State realtor associations | 100+ |
| Education | University admissions forms | 200+ |
| Legal | Court forms (state/federal) | 300+ |
| Surveys | Public domain survey templates | 50+ |

**Minimum viable dataset:** 100 PDFs across 5+ categories
**Recommended dataset:** 1,000+ PDFs across all categories
**Ideal dataset:** 10,000 PDFs with augmentation for robustness