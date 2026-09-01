# SugboDoc — User Documentation

*"SugboDoc — better healthcare together."*

SugboDoc is a cloud-based clinic and practice management platform for healthcare
providers. It covers the full patient journey — scheduling, registration,
clinical encounters and documentation, immunizations, billing and payments — plus
the administrative setup behind it: staff accounts, departments, resources,
locations, document templates, and subscriptions.

This guide is organized by module. Most day-to-day clinical work happens inside a
**patient record**, which is made up of *cards* (Appointments, Encounters, Vital
Signs, SOAP Notes, Diagnosis, Clinical Notes, Prescriptions, Service Requests,
Uploaded Files, Immunizations, Bills & Payment). Administrative work happens in
dedicated sidebar modules.

> This documentation was reconstructed from the [SugboDoc full tutorial video](https://www.youtube.com/watch?v=c2WEOZnOhps).
> Chapter timestamps are cited as `[mm:ss]` for reference. A few chapter titles in
> the source were mislabeled; the corrected topic is used here and noted where
> relevant.

---

> **Sample excerpt.** This repo ships a trimmed public excerpt of the SugboDoc
> knowledge base so the assistant, the tests, and the eval harness run out of the
> box. The full documentation is swapped in privately by placing it at
> `docs/SugboDoc-Documentation.md` (which is git-ignored); `config.DOCS_PATH`
> uses that file when present and falls back to this excerpt otherwise.



## Table of contents

1. [Core concepts](#core-concepts)
2. [Schedule module](#schedule-module)
3. [Patients (Patient Worklist)](#patients-patient-worklist)
4. [Appointments](#appointments)
5. [Encounters (Patient Visits)](#encounters-patient-visits)
6. [Vital Signs](#vital-signs)
7. [SOAP Notes](#soap-notes)
8. [Diagnosis](#diagnosis)
9. [Clinical Notes](#clinical-notes)
10. [Clinical Notes Templates](#clinical-notes-templates)
11. [Prescriptions](#prescriptions)
12. [Service Requests](#service-requests)
13. [Uploaded Files](#uploaded-files)
14. [Immunizations](#immunizations)
15. [Bills & Payment (patient record)](#bills--payment-patient-record)
16. [Charges (Bills & Payments setup)](#charges-bills--payments-setup)
17. [Staff Management](#staff-management)
18. [Departments](#departments)
19. [Resources](#resources)
20. [Locations (Branches)](#locations-branches)
21. [Facility Settings — Document Templates](#facility-settings--document-templates)
22. [Subscriptions](#subscriptions)

---



## Core concepts


| Term                                   | Meaning                                                                                                                                                           |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Patient Worklist**                   | Your list of patients. Entry point to every patient record.                                                                                                       |
| **Patient record**                     | A patient's profile, containing all clinical and billing *cards*.                                                                                                 |
| **Card**                               | A section within the patient record (e.g. Vital Signs card, Diagnosis card). Each card has an **Add** button and a **View all** option.                           |
| **Encounter / Patient Visit**          | A single episode of care. Most clinical entries (SOAP notes, diagnosis, prescriptions, immunizations, invoices, etc.) are *linked to an encounter*.               |
| **Healthcare provider / Practitioner** | The doctor or nurse delivering care.                                                                                                                              |
| **Location / Branch**                  | A clinic or facility site. Can be **internal** (your own consultation sites) or **external** (sites where practitioners are only affiliated — rounds, surgeries). |
| **Grayed-out fields**                  | On edit screens, only non-grayed fields can be changed.                                                                                                           |
| **Short codes**                        | Template variables (e.g. patient full name, age, address, diagnosis) that auto-fill with patient data when a document is generated.                               |
| **Export (A4 / A5)**                   | Clinical documents (prescriptions, service requests, certificates) can be printed or downloaded as PDF in A4 or A5 paper size.                                    |


**General editing pattern (applies to most cards):**

1. Open the patient record from the Patient Worklist.
2. Locate the card → **View all**.
3. Select the item → **three dots** (or arrow) → **Edit** / **View** / **Void**.
4. Change the allowed fields → review → **Submit** / **Update** / **Save**.

---



## Schedule module

*Chapter: Add Schedule [00:11]*

Defines a practitioner's recurring availability so appointments can be booked
against real time slots.

**Create a schedule**

1. Sidebar → **Schedule** → **All Schedule**.
2. Click **Add new** → the *Add Schedule* modal opens.
3. Set the fields:
  - **Location** — where the schedule applies.
  - **Healthcare provider** — who the schedule is assigned to.
  - **Appointment duration** — length of each slot.
  - **Days available** — select the weekdays (e.g. Monday, Wednesday, Friday).
  - **Time slots** — click the **+** on the right to add a slot and set its
  start/end time. Multiple time slots per day are allowed.
4. Review the added schedule for accuracy.
5. Click **Add** to save.

---



## Patients (Patient Worklist)

*Chapter: Adding of Patient [01:24]*

The Patient Worklist is your roster of patients. New patients are added either by
creating a fresh profile or by linking an existing SugboDoc account.

### Add a new patient

1. Sidebar → **Patient Worklist** → **Add patient**.
2. Choose **Add new patient**.
3. Fill in the patient's details:
  - Personal information
  - Contact information
  - Address (if applicable)
  - **Related person** (optional): relationship to patient, personal
  information, address — then click **Add** for that person.
  - Profile photo (optional).
4. Click **Add**. A confirmation message confirms the patient was created.



### Add a patient via search

Use this only when the patient **already has a SugboDoc account** but is not yet
on your list.

1. **Add patient** → **Via search**.
2. Choose a search method:
  - **Patient number** — enter the patient's SugboDoc number, first name, and
   last name.
  - **Patient details** — search by identifying details.
3. Click **Search**.
4. In the results, find the correct patient → **Add patient**.
5. A confirmation message confirms they were added to your list.

---



## Appointments

Located on the **Appointment card** inside the patient record.

### Create an appointment

*Chapter: Appointment Creation [03:11]*

1. Open the patient record → **Appointment card** → **Add**.
2. Fill in the details:
  - **Healthcare provider**
  - **Location**
  - **Appointment service**
  - **Appointment date** and **preferred slot**
  - **Appointment status**:
    - **Pending** — patient is still unsure.
    - **Booked** — patient has confirmed.
  - **Reason for visit**
3. Review → **Submit**.



### Update an appointment

*Chapter: Update Appointment [04:26]*

1. Patient record → **Appointment card** → **View all**.
2. Select the appointment → **Edit**.
3. Editable fields only (non-grayed): **service, date, available slots,
  appointment status, reason for visit**.
4. Review → **Submit**.

---



## Encounters (Patient Visits)

An encounter represents one visit/episode of care. Located on the **Encounter
card**.

### Create an encounter

*Chapter: Encounter Creation [05:23]*

1. Sidebar → **Patient Worklist** → open the patient profile.
2. **Encounter card** → **Add encounter**.
3. Select an **encounter type** (pop-up modal).
4. Enter the encounter details:
  - **Encounter status** — e.g. *Patient is receiving care*.
  - **Encounter source** — optional (may be left blank).
  - **Encounter location** — which clinic serves as the location.
  - **Reason for visit**.
5. Click **Submit**.



### Update / end an encounter

*Chapter: Update Encounter [06:28]*

1. Patient record → **Encounter card** → **View all encounters**.
2. Choose the encounter → **three dots** → **Edit encounter**.
3. Change the **encounter status** to reflect the situation — e.g. *Encounter
  completed and patient departed* to end it.
4. Click **Submit**.

---



## Vital Signs

Located on the **Vital Signs card**.

### Add vital signs

*Chapter: Add Vital Signs [07:14]*

1. Patient Worklist → open the patient profile.
2. **Vital Signs card** → **Add vitals**.
3. Optionally link an **encounter**.
4. Enter the measured values: **height, weight, blood pressure, temperature,
  respiration level** (and other available fields).
5. Add **notes** about the patient's condition or the readings (optional).
6. Click **Submit**.



### Edit vital signs

*Chapter: Edit Vital Signs [08:09]*

1. Patient record → **Vital Signs card** → **View all vital signs**.
2. Choose the record → **three dots** → **Edit**.
3. Add or update any values (e.g. add **SPO2**) and update the **notes**.
4. Review → **Submit**.

---



## SOAP Notes

Structured clinical notes: **S**ubjective, **O**bjective, **A**ssessment,
**P**lan. Located on the **SOAP Notes card**.

### Create SOAP notes

*Chapter: SOAP Notes Creation [09:05]*

1. On the patient record, find the **SOAP Notes card** → **Add SOAP notes**.
2. Choose the **encounter** to link the notes to.
3. Enter the **Subjective, Objective, Assessment, and Plan** sections.
4. Optionally tick the checkbox to allow **other care team members** to view the
  notes.
5. Click **Submit**. The notes appear in the patient's record.



### Edit SOAP notes

*Chapter: Edit SOAP Notes [10:06]*

1. Patient record → **SOAP Notes card** → **View all SOAP notes**.
2. Choose the notes → **arrow down** → **Edit**.
3. Editable fields only (non-grayed): **title** and the **SOAP notes** fields.
  You can also **add images** to a section (e.g. add an image to *Objective*,
   add detail to *Plan*).
4. Review → **Submit**.

---



## Diagnosis

Located on the **Diagnosis card / section**.

### Create a diagnosis

*Chapter: Diagnosis Creation [11:08]*

1. Patient Worklist → open the patient profile.
2. **Diagnosis section** → **Add diagnosis**.
3. Choose the **encounter** to link the diagnosis to.
4. Enter:
  - **Diagnosis**
  - **Diagnosis rank**
  - **Diagnosis date**
  - **Diagnosis note** (if applicable)
5. Review → **Submit**.
6. View the entry any time with the **Details** button.



### Edit a diagnosis

*Chapter: Edit Diagnosis [12:07]*

1. Patient record → **Diagnosis card** → **View all diagnosis**.
2. Choose the diagnosis → **three dots** → **Edit**.
3. Click **See more** to expand all fields. Editable fields (non-grayed):
  **onset date, diagnosis rank, diagnosis date, clinical status, verification
   status, diagnosis note**.
4. Review → **Submit**.

---



## Clinical Notes

Free-form, template-driven clinical documentation. Located on the **Clinical
Notes card**. Templates are managed separately (see
[Clinical Notes Templates](#clinical-notes-templates)).

### Create clinical notes

*Chapter: Clinical Notes Creation [13:12]*

1. Open the patient record → **Clinical Notes card** → **Add clinical notes**.
2. Set up the note:
  - **Encounter** to link to.
  - **Template** — select a previously created template.
  - **Attending doctor**.
  - **Category** — selecting one pre-fills the **title** (the title can still be
  changed).
3. Because a template is selected, the **details auto-populate** and **short
  codes** fill in with the patient's data.
4. Add or modify information in the **Clinical Notes details** section as needed.
5. **Show patient banner** / **Show title** toggles — adjust from their defaults
  (e.g. turn **Show patient banner** off).
6. Review → **Submit**.



### Edit clinical notes

*Chapter: Edit Clinical Notes [14:28]*

1. Patient record → **Clinical Notes card**. Either:
  - Click **Edit** directly, or
  - **View all clinical notes** → select the note → **three dots** → **Edit**.
2. Editable fields only (non-grayed): **template, category, title, details**.
3. You can also change the **Show patient banner** and **Show title** toggles.
4. Review → **Submit**.

---



## Clinical Notes Templates

*Chapter: (labeled "Clinical Notes Creation") [15:31]*

Reusable templates that speed up clinical note creation by embedding **short
codes** — variables that auto-fill with patient data.

**Create a template**

1. Sidebar → **Clinical Notes** → **Clinical Notes Templates**.
2. Click **Add template**.
3. Enter a **title** for the template.
4. Set the **Show patient banner** / **Show title** toggles to control what
  appears on notes generated from this template (e.g. toggle **Show title** on).
5. In the template creation area, build the body using **short codes** — e.g.
  short codes for the patient's **full name, age, address, and diagnosis** — so
   these details are filled automatically instead of typed manually.
6. Click **Submit** to save the template.

---



## Prescriptions

Located on the **Prescription card**.

### Create a prescription

*Chapter: Prescription Creation [16:45]*

1. Patient Worklist → open the patient profile.
2. **Prescription card** → **Add prescription**.
3. Select the **attending doctor** and the **encounter** to link to.
4. **Add medication** → **Add medicine**:
  - Search and select a medication from the list.
  - Specify **SIG** (directions), **uses**, and **quantity**.
  - Click **Add**.
5. **If the medication is not listed** → **Create new medication**:
  - Enter **generic name, brand name, dosage, strength, form, uses, side
   effects**.
  - Click **Create**, then add the newly created medicine (found under the
  **Custom** category) with its SIG and quantity → **Add**.
6. Optionally tick the checkbox to **schedule the patient's next appointment** and
  pick the date.
7. Add **additional notes** if needed.
8. Click **Submit** → review the medication list → **Confirm and submit**.



### View / export a prescription

*Chapter: (labeled "Diagnosis Creation") [18:19]*

1. Patient record → **Prescription card**. Either **Details**, or **View all
  prescriptions** → select → **three dots** → **View**.
2. In the modal, click **View prescription** (upper-right). A full prescription
  page opens.
3. **Export**: **Print** or **Download**, choosing paper size **A4** or **A5**.
  Selecting a size with the **PDF** option renders the prescription in that size;
   downloads are saved in the selected size.

---



## Service Requests

Orders for services/procedures to be rendered. Located on the **Service Request
card**.

### Create a service request

*Chapter: Service Requests Creation [19:31]*

1. Patient Worklist → open the patient profile.
2. **Service Request card** → **Add service request**.
3. Select the **encounter** to link to.
4. **Add new service**:
  - Optionally tick the checkbox to specify the **renderer** — **department,
   facility, or practitioner** that should handle the order.
  - Search and select a **service** from the list.
  - Specify the **instruction**.
  - Click **Add**.
5. **If the service is not listed** → **Create new service**:
  - Select a **category**, enter the **service name** → **Add to service list**.
  - Search for the new (custom) service, select it, specify the instruction →
  **Add**.
6. You can **view**, **edit**, or **remove** each added service before submitting.
7. Review → **Submit**.



### Edit a service request

*Chapter: Edit Service Request [21:13]*

1. Patient record → **Service Request card** → **View all service requests**.
2. Choose the request → **three dots** → **Edit**.
3. You can **update a service's details**, **add a new service**, or **remove a
  service**.
4. Review → **Submit**.



### View / export a service request

*Chapter: View Service Request [22:31]*

1. Patient record → **Service Request card** → **View all service requests**.
2. Select the request → **three dots** → **View**. A full details page opens.
3. **Export**: **Print** or **Download**, paper size **A4** or **A5** (PDF renders
  and downloads in the selected size).

---



## Uploaded Files

*Chapter: Upload Files [23:33]*

Attach images or PDFs to a patient's record. Located on the **Uploaded Files
card**.

1. Patient record → **Uploaded Files card** → **Add**.
2. Optionally associate the file with an **encounter**.
3. Choose a **category** for the file.
4. Enter a **title** and **description**.
5. Upload the file(s):
  - Image or PDF.
  - Up to **5 files**, of mixed types.
6. Click **Add file** to complete.

---



## Immunizations

Located on the **Immunization card**. Two record types:


| Type                      | Use when                                                                                                                                         |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Internal immunization** | The current practitioner **administers the vaccine and creates the record**.                                                                     |
| **External immunization** | The vaccine was administered by **another practitioner and not recorded by them**; the current practitioner records it to keep history complete. |




### Add an internal immunization

*Chapter: Add Internal Immunization [24:34]*

1. Patient record → **Immunization card** → **Add** → **Add internal
  immunization**.
2. Select the **encounter** to link to.
3. **Add vaccine** → search for and select the vaccine → **Next**.
4. Fill in: **dosage, lot number, expiration date, date & time administered,
  site, route, vaccination site, reaction**. Add **images** if applicable.
5. Click **Add** to record the vaccine. Add more vaccines if needed.
6. Click **Submit** → review the **immunization preview** → **Confirm and
  submit**.



### Add an external immunization

*Chapter: Add External Immunization [26:31]*

1. Patient record → **Immunization card** → **Add** → **Add external
  immunization**.
2. Search for and select the vaccine → **Next**.
3. On the *Add vaccine* screen:
  - Optionally tick the box if there is **proof** of the external immunization
   (baby's book, vaccination certificate, etc.).
  - Enter the **name of the practitioner** who previously vaccinated the patient.
  - Select the **facility** where it took place.
4. Fill in: **dosage, lot number, expiration date, date & time administered,
  site, route, reaction**.
5. Add an **image as proof** of the previous vaccination.
6. Click **Add** to record the immunization.



### View / export immunizations

*Chapter: View Immunization [28:26]*

1. Patient record → **Immunization card** → **View all**.
2. The **form view** shows by default. Use the top-left toggle to switch to
  **list view** (more organized).
3. List view tabs:
  - **All vaccine** — every vaccine given to the patient (internal or external).
  - **By encounter** — vaccines grouped by encounter.
  - **Created by me** — vaccines administered by the currently logged-in user.
4. **Certificate**: click **Certificate** → **Print** or **Download**, paper size
  **A4** or **A5** (PDF formats to the selected size).

---



## Bills & Payment (patient record)

Located on the **Bills and Payment card**. Handles invoices, charges, deposits,
and voids for a specific patient.

### Create an invoice — patient pays upfront (Paid)

*Chapter: Invoice Creation (Paid) [30:07]*

1. Patient record → **Bills and Payment** section → **Add invoice**.
2. Select the **encounter** to link to.
3. Choose the **invoice due type**.
4. Upper-right → **Add charge**. Choose a charge type:
  - **Co-pay** — two or more parties contribute to the charge.
  - **Self-pay** — the patient covers the charge alone.
  - **Insurance** — covered by the patient's insurance provider.
5. Select **Self-pay**, pick a charge from the list → **Add**.
6. Enter the **payment amount** the patient pays upfront (add a **note** if
  needed). The **total amount** updates to reflect what remains (e.g. reads `0`
   when fully paid).
7. Click **Submit** → on the review prompt, **Continue** to finalize.



### Create an invoice — bill for later (Unpaid)

*Chapter: Invoice Creation (Unpaid) [31:39]*

1. Patient record → **Bills and Payment card** → **Add**.
2. Select the **encounter** to link to.
3. Update the **invoice date** or leave as is.
4. Select the **invoice due type** to define the due date (e.g. *Due on
  receipt*).
5. Upper-right → **Add charge** → select charges based on services rendered
  (e.g. *Face-to-face consultation fee*). Add more as needed → **Add**.
6. On the **item summary**:
  - Adjust **quantities** if necessary.
  - Click the **See more** icon on a charge to view **tax, practitioner/facility
  charge, convenience fee**.
  - Add **discounts** or **promo codes** if applicable.
7. Review → **Submit**.



### Add a deposit to an unpaid invoice

*Chapter: Add Deposit [33:08]*

1. Patient record → **Bills and Payment card** → **View all**.
2. Locate the **Unpaid invoices** card → **Deposit** button (right side).
3. In the prompt, click the **down arrow** next to the invoice to see details.
4. Click **Deposit** → select **Personal**.
5. Enter the **amount** to be paid (match the intended deposit amount).
6. Click **Confirm deposit**. A modal confirms the deposit.



### Void a payment

*Chapter: Void Payment [34:05]*

1. Patient record → **Bills and Payment card** → **View all**.
2. Upper-right → **View all deposit**.
3. Identify the deposit → **down arrow** for details.
4. **Three dots** next to the deposit → options **View** and **Void**.
  - **View** shows the deposit details.
  - **Void** opens a confirmation prompt → click **Void** to finalize.

---

*(Excerpt ends here. The full knowledge base continues with Charges, Staff
Management, Departments, Resources, Locations, Document Templates and
Subscriptions.)*
